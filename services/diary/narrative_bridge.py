"""剧本人设插件握手桥（mai-diary ↔ glcoge.mai-narrative）。

职责（对应设计树 mount-points §2-8「日记插件握手」）：

1. **会话分诊**：判定时间窗内消息是否来自「剧本模式会话」。
   是 → 日记作者人格改用剧本自我层（锚定 identity + 心情 + 作息）；
   否 → 沿用全局 `personality.*` 旧逻辑。
2. **编年史写入**：日记成功落盘后，把成品幂等追加到自我层编年史
   （``scope=self, kind=diary``；同一天重跑不重复写）。

降级纪律：narrative 未加载 / 未启用 / 调用失败，一律降级回旧逻辑，
**不阻塞日记生成与推送**（握手是附加动作，不是主流程前置条件）。

跨插件调用依赖主程序 ``api.call``（目标 API 必须 ``public=True``，
本插件 manifest 需声明 ``api.call`` capability）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import asyncio

from ...utils import get_logger
from .message import is_private, msg_user_id

logger = get_logger(__name__)

# narrative 插件 ID（_manifest.json）
_NARRATIVE_PLUGIN_ID = "glcoge.mai-narrative"
_CONTEXT_API = f"{_NARRATIVE_PLUGIN_ID}.narrative_diary_context"
_APPEND_API = f"{_NARRATIVE_PLUGIN_ID}.narrative_chronicle_append"


class NarrativeBridge:
    """narrative 插件握手客户端：所有失败路径返回 None / False，绝不抛出。

    Args:
        plugin: mai-diary 插件实例（读取 ``config.narrative`` 与 ``ctx``）。
    """

    def __init__(self, plugin) -> None:
        self._plugin = plugin
        self._ctx = plugin.ctx
        self._cfg = plugin.config.narrative
        # 进程内可用性缓存：None=未探测，True/False=结果
        self._available: Optional[bool] = None

    # ===== 可用性 =====

    async def _probe_available(self) -> bool:
        """探测 narrative 插件是否对本插件可见（一次 RPC，失败不再重试）。"""
        if self._available is not None:
            return self._available
        try:
            apis = await self._ctx.api.list(plugin_id=_NARRATIVE_PLUGIN_ID)
            self._available = isinstance(apis, list) and bool(apis)
        except Exception as exc:
            logger.debug("narrative 插件探测失败（将降级为旧逻辑）: %s", exc)
            self._available = False
        return self._available

    async def _call_api(self, api_name: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """带超时与异常兜底的跨插件 API 调用。"""
        try:
            # api_timeout_seconds 是 config.py NarrativeSection 的确定字段（AGENTS.md 类属性规范）
            timeout = max(2, int(self._cfg.api_timeout_seconds or 10))
            result = await asyncio.wait_for(
                self._ctx.api.call(api_name, **kwargs),
                timeout=timeout,
            )
        except Exception as exc:  # TimeoutError 也属于 Exception
            logger.warning("调用 %s 失败（降级为旧逻辑）: %s", api_name, exc)
            return None
        if not isinstance(result, dict):
            logger.debug("调用 %s 返回非 dict（降级）: %s", api_name, type(result).__name__)
            return None
        return result

    # ===== 会话分诊 =====

    async def fetch_diary_context(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        date: str = "",
    ) -> Optional[Dict[str, Any]]:
        """获取剧本模式判定 + 自我层人格摘要。

        Args:
            messages: 本条日记时间窗内的消息（用于判定是否存在剧本模式会话）。
            date: **被写日记的日期**（``YYYY-MM-DD``）。本插件 04:00 跑的是
                **昨天**那篇，必须显式传给 narrative —— 否则它会按"今天"取
                当日生活片段，凌晨这一跑必然取空。旧版 narrative 不认这个
                入参（``**kwargs`` 丢弃），行为等同不传，安全降级。

        Returns:
            ``None``：narrative 未启用 / 不可用 / 调用失败（走旧逻辑）。
            dict：``{"use_self_persona": bool, "data": <narrative_diary_context 原始返回>}``
        """
        if not self._cfg.enabled:
            return None
        if not await self._probe_available():
            return None

        data = await self._call_api(_CONTEXT_API, date=str(date or "").strip())
        if data is None or not bool(data.get("ok")):
            return None
        if not bool(data.get("narrative_enabled")):
            logger.info("narrative 插件已加载但剧本模式未启用，日记沿用全局人格")
            return None

        use_self_persona = self._has_mode_session(messages, data)
        if not use_self_persona:
            logger.info("时间窗内无剧本模式会话（剧本用户=%s），日记沿用全局人格",
                        ",".join(str(x) for x in (data.get("mode_user_ids") or [])) or "无")
            return None
        return {"use_self_persona": True, "data": data}

    @staticmethod
    def _has_mode_session(
        messages: Optional[List[Dict[str, Any]]],
        data: Dict[str, Any],
    ) -> bool:
        """消息中是否存在剧本模式会话（显式 stream 白名单或私聊用户白名单）。"""
        mode_stream_ids = {str(item) for item in (data.get("mode_stream_ids") or [])}
        mode_user_ids = {str(item) for item in (data.get("mode_user_ids") or [])}
        if not mode_stream_ids and not mode_user_ids:
            return False
        for msg in messages or []:
            if not isinstance(msg, dict):
                continue
            session_id = str(msg.get("session_id") or "")
            if session_id and session_id in mode_stream_ids:
                return True
            user_id = msg_user_id(msg)
            if not user_id or user_id not in mode_user_ids:
                continue
            # 私聊判定：统一走 message.is_private（规则对齐主程序 message.py:61，避免群聊里同号误判）
            if is_private(msg):
                return True
        return False

    # ===== 编年史写入（幂等） =====

    async def append_chronicle(self, date: str, content: str) -> Dict[str, Any]:
        """把当日日记成品写入自我层编年史（幂等）。

        Returns:
            dict: ``{"ok": bool, "written": bool, "reason": str}``。
            ``ok=False`` 只记日志，调用方不得据此失败主流程。
        """
        fallback = {"ok": False, "written": False, "reason": "unavailable"}
        if not self._cfg.enabled:
            return {"ok": False, "written": False, "reason": "disabled"}
        if not await self._probe_available():
            return fallback

        result = await self._call_api(
            _APPEND_API,
            date=str(date or "").strip(),
            content=str(content or "").strip(),
        )
        if result is None:
            return fallback
        return {
            "ok": bool(result.get("ok", False)),
            "written": bool(result.get("written", False)),
            "reason": str(result.get("reason") or ""),
        }


__all__ = ["NarrativeBridge"]