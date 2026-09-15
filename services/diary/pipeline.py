"""日记 pipeline：消息抓取 → 时间线 → prompt → LLM → 截断 → 落盘。"""

from __future__ import annotations

import datetime
import random
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from ...utils import (
    date_with_weather,
    diary_window_for_date,
    estimate_tokens,
    get_global_str,
    smart_truncate,
    truncate_by_tokens,
)
from ...utils import get_logger
from .fetcher import MessageFetcher
from .llm_runner import LLMRunner
from .narrative_bridge import NarrativeBridge
from .prompts import build_brief_prompt, build_diary_prompt, build_narrative_status
from .storage import DiaryStorage
from .timeline import TimelineBuilder, weather_by_emotion

logger = get_logger(__name__)


def _parse_target_chats(s: str) -> List[str]:
    """配置中 target_chats 是多行字符串，按行拆。"""
    if not s:
        return []
    return [line.strip() for line in s.replace("\r", "").split("\n") if line.strip()]


class DiaryPipeline:
    """日记主流程编排。

    时间窗固定为 ``[diary_date 04:00, diary_date+1 04:00)``（24h 滚动）。
    触发时间（如 04:00）由 scheduler 控制；本类只关心某条 ``diary_date`` 的生成。
    """

    def __init__(self, plugin) -> None:
        self._plugin = plugin
        self._ctx = plugin.ctx
        self._cfg = plugin.config
        self._storage = DiaryStorage(base_dir=self._cfg.output.base_dir)
        self._fetcher = MessageFetcher(plugin.ctx)
        self._llm = LLMRunner(
            plugin.ctx,
            plugin.config.llm.text_model,
            timeout=plugin.config.llm.timeout_seconds,
        )
        # 剧本人设插件握手（于 2026-08-30 适配新架构；失败自动降级，不影响主流程）
        self._bridge = NarrativeBridge(plugin)

    @property
    def storage(self) -> DiaryStorage:
        return self._storage

    # ===== 公开入口 =====

    async def generate_for_date(self, date: str) -> Tuple[bool, str, bool]:
        """生成指定日期（YYYY-MM-DD）对应的日记。

        时间窗：``[date 04:00, date+1 04:00)``，由配置 ``schedule.timezone_offset_hours``
        间接影响（调用方传入的 ``date`` 已按目标时区换算好）。

        Returns:
            ``(ok, message, retryable)``。``retryable`` 仅当 ``ok=False`` 时有意义：
            软失败（LLM 空返回 / 异常）为 True，硬失败（消息数不足，窗口已闭合、
            重试无意义）为 False。成功时统一为 False。
        """
        start_time, end_time, label = diary_window_for_date(
            date, cutoff_hour=self._compute_cutoff_hour()
        )
        target_chats = _parse_target_chats(self._cfg.message.target_chats)

        messages = await self._fetcher.fetch_with_filter(
            self._cfg.message.filter_mode,
            target_chats,
            start_time,
            end_time,
        )

        min_per_chat = self._cfg.message.min_messages_per_chat
        if min_per_chat > 0:
            before = len(messages)
            messages = MessageFetcher.filter_min_messages_per_chat(messages, min_per_chat)
            if before != len(messages):
                logger.info(
                    "min_messages_per_chat=%d 过滤后消息 %d → %d",
                    min_per_chat, before, len(messages),
                )

        min_count = self._cfg.message.min_message_count
        if len(messages) < min_count:
            # 硬失败：时间窗已闭合，重试不会改变消息数，因此不可重试
            return False, f"消息数量不足({len(messages)}/{min_count})", False

        return await self._generate_from_messages(label, messages, start_time, end_time)

    # ===== 内部 =====

    def _compute_cutoff_hour(self) -> int:
        """从 schedule.generate_time 取 HH，作为 cutoff_hour。

        例：``"04:00"`` → 4；``"23:30"`` → 23。
        """
        from ...utils.date import parse_clock
        parsed = parse_clock(self._cfg.schedule.generate_time)
        if parsed is None:
            logger.warning(
                "schedule.generate_time 格式错误 (%s)，回退 4",
                self._cfg.schedule.generate_time,
            )
            return 4
        return parsed[0]

    async def _resolve_personality(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, str, str, Optional[Dict[str, Any]]]:
        """解析日记作者人格（含剧本人设「会话分诊」）。

        Triage 规则（对应剧本人设设计树 mount-points §2-8）：
        - 若时间窗内存在剧本模式会话 → 作者人格改用剧本「自我层」
          （锚定 identity + 心情 + 作息），避免日记读出来是默认人格的割裂；
        - 否则沿用主程序全局 ``personality.*`` 旧逻辑。

        Returns:
            ``(personality, expression, bot_qq, narrative_ctx)``。
            ``narrative_ctx`` 为 None 表示未走剧本路径（或分诊不适用）。
        """
        if not self._cfg.summary.use_bot_personality:
            return "", "", "", None

        bot_qq = await get_global_str(self._ctx, "bot.qq_account", "")

        # 剧本人设分诊：剧本模式会话 → 自我层人格
        if self._cfg.narrative.enabled:
            narrative_ctx = await self._bridge.fetch_diary_context(messages)
            if narrative_ctx is not None:
                data = narrative_ctx.get("data") or {}
                self_state = data.get("self_state") or {}
                personality = str(self_state.get("identity_persona") or "")
                expression = str(self_state.get("expression_hint") or "")
                if not personality:
                    personality = bot_qq or "一个角色"
                return personality, expression, bot_qq, narrative_ctx

        # 旧逻辑：主程序全局人格
        personality = await get_global_str(self._ctx, "personality.personality", "")
        expression = await get_global_str(self._ctx, "personality.expression_style", "")
        if not personality:
            personality = bot_qq or "一个角色"
        return personality, expression, bot_qq, None

    async def _generate_from_messages(
        self,
        date: str,
        messages: List[Dict[str, Any]],
        start_time: float,
        end_time: float,
    ) -> Tuple[bool, str, bool]:
        """从已抓取的消息生成日记。返回 ``(ok, message, retryable)``。"""
        try:
            personality, expression, bot_qq, narrative_ctx = await self._resolve_personality(messages)

            timeline_builder = TimelineBuilder(
                bot_qq_account=bot_qq,
                per_message_max_chars=self._cfg.message.per_message_max_chars,
            )
            timeline = timeline_builder.build(messages)

            max_tokens = max(1000, int(self._cfg.llm.truncate_tokens or 50000))
            if estimate_tokens(timeline) > max_tokens:
                timeline = truncate_by_tokens(timeline, max_tokens)

            weather = weather_by_emotion(messages)
            date_str = date_with_weather(date, weather)

            min_wc = self._normalize_int(
                self._cfg.summary.min_word_count, default=250, lo=20, hi=8000
            )
            max_wc = self._normalize_int(
                self._cfg.summary.max_word_count, default=400, lo=20, hi=8000
            )
            if max_wc < min_wc:
                max_wc = min_wc
            target_length = random.randint(min_wc, max_wc)

            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            bot_personality = (personality or "") + (
                ("，表达方式：" + expression) if expression else ""
            )
            bot_personality = bot_personality or "一个角色"

            # 剧本人设当日状态（自我层 mood → prompt，供日记口吻对齐；无则空）
            narrative_status = ""
            if narrative_ctx is not None:
                narrative_status = build_narrative_status(narrative_ctx)

            style = self._cfg.summary.style
            if style == "brief":
                prompt = build_brief_prompt(
                    date=date,
                    timeline=timeline,
                    date_with_weather=date_str,
                    target_length=target_length,
                    bot_personality=bot_personality,
                    style_desc=expression or "",
                    self_description=self._cfg.summary.self_description,
                    current_time=current_time,
                    narrative_status=narrative_status,
                    template=self._cfg.summary.custom_prompt,
                )
            else:
                prompt = build_diary_prompt(
                    date=date,
                    timeline=timeline,
                    date_with_weather=date_str,
                    target_length=target_length,
                    bot_personality=bot_personality,
                    style_desc=expression or "",
                    self_description=self._cfg.summary.self_description,
                    current_time=current_time,
                    narrative_status=narrative_status,
                    template=self._cfg.summary.custom_prompt if style == "custom" else "",
                )

            if self._cfg.llm.show_prompt:
                logger.info("日记 prompt（前 500 字）: %s", prompt[:500])

            ok, text = await self._call_model(prompt)
            if not ok:
                # text 此时是**具体失败原因**（超时秒数 / 异常文本 / success=False 的
                # error）——2026-09-15 之前这一步被写成 ``text if success else ""``，
                # 原因被吞掉，导致落盘与推送只能报一句"模型返回空内容"。
                reason = (text or "").strip() or "模型调用失败（未返回原因）"
                await self._save_failed(
                    date, weather, reason, timeline_builder.stats,
                    detail=self._error_detail(reason, len(prompt)),
                )
                return False, f"模型生成日记失败：{reason}", True

            content = (text or "").strip()
            if not content:
                # 与上一种"空"区分开：调用成功但正文为空，排查方向完全不同
                # （多半是模型侧被截断 / 输出被过滤，而不是网络或超时）
                reason = "模型返回空内容（调用成功但正文为空）"
                await self._save_failed(
                    date, weather, reason, timeline_builder.stats,
                    detail=self._error_detail(reason, len(prompt)),
                )
                return False, f"模型生成日记失败：{reason}", True

            if len(content) > max_wc:
                content = smart_truncate(content, max_wc)

            await self._storage.save_diary(
                {
                    "date": date,
                    "diary_content": content,
                    "word_count": len(content),
                    "generation_time": time.time(),
                    "weather": weather,
                    "bot_messages": timeline_builder.stats["bot_messages"],
                    "user_messages": timeline_builder.stats["user_messages"],
                    "window_start": start_time,
                    "window_end": end_time,
                    "style": style,
                    "status": "生成成功",
                    "error_message": "",
                },
                write_markdown=self._cfg.output.write_markdown,
                markdown_header_template=self._cfg.output.markdown_header_template,
                markdown_footer_template=self._cfg.output.markdown_footer_template,
            )
            # 防重复状态始终落盘：last_diary_date 仅作状态展示/追溯，
            # 补生成判定已改为按日记数据存在性（不受 persist_state 门控）
            self._storage.write_last_diary_date(date)

            # 剧本人设握手：把当日日记成品追加到自我层编年史（幂等，失败不阻塞）
            if narrative_ctx is not None:
                result = await self._bridge.append_chronicle(date, content)
                if result.get("written"):
                    logger.info("已写入剧本人设编年史（scope=self, date=%s）", date)
                elif result.get("ok"):
                    logger.info("编年史跳过写入（%s）：%s", date, result.get("reason") or "duplicate")
                else:
                    logger.warning(
                        "编年史写入失败（%s，日记本身不受影响）: %s",
                        date, result.get("reason") or "unavailable",
                    )
            return True, content, False
        except Exception as exc:
            logger.error("生成日记失败: %s", exc, exc_info=True)
            try:
                await self._save_failed(
                    date, "阴", str(exc), {"bot_messages": 0, "user_messages": 0},
                    detail=self._error_detail(str(exc), 0, stack=traceback.format_exc()),
                )
            except Exception:
                pass
            return False, f"生成日记时出错: {exc}", True

    async def _call_model(self, prompt: str) -> Tuple[bool, str]:
        """调用模型，返回 ``(ok, text_or_reason)``。

        失败时第二个返回值是**具体原因**，必须由调用方带出去
        （落盘 + 推送 + 错误日志），不要再吞成空串。
        """
        return await self._llm.generate(
            prompt, temperature=self._cfg.llm.temperature, max_tokens=4096
        )

    def _error_detail(self, reason: str, prompt_chars: int, stack: str = "") -> str:
        """拼完整报错：短原因 + 排查上下文（+ 异常堆栈），供 errors/*.log 落盘。"""
        parts = [
            reason,
            f"model={self._cfg.llm.text_model}",
            f"timeout={self._cfg.llm.timeout_seconds}s",
            f"truncate_tokens={self._cfg.llm.truncate_tokens}",
            f"prompt_chars={prompt_chars}",
        ]
        if stack:
            parts.append("堆栈:\n" + stack)
        return "\n".join(parts)

    async def _save_failed(
        self,
        date: str,
        weather: str,
        error_message: str,
        stats: Dict[str, int],
        detail: str = "",
    ) -> None:
        """保存失败记录。

        ``error_message`` 只放一行短原因（要推 ntfy）；``detail`` 是完整报错
        （含堆栈与上下文），单独追加到 ``errors/YYYY-MM-DD.log``。
        """
        # 完整报错先落盘：即便下面 save_diary 也失败，也不至于连原因一起丢
        self._storage.append_error_log(date, detail or error_message)
        try:
            await self._storage.save_diary(
                {
                    "date": date,
                    "diary_content": "",
                    "word_count": 0,
                    "generation_time": time.time(),
                    "weather": weather,
                    "bot_messages": stats.get("bot_messages", 0),
                    "user_messages": stats.get("user_messages", 0),
                    "style": "",
                    "status": "报错:生成失败",
                    "error_message": f"原因:{error_message}",
                },
                write_markdown=False,
            )
        except Exception as exc:
            logger.error("保存失败记录出错: %s", exc)

    @staticmethod
    def _normalize_int(value: Any, *, default: int, lo: int, hi: int) -> int:
        if not isinstance(value, int):
            return default
        if value < lo:
            return lo
        if value > hi:
            return hi
        return value


__all__ = ["DiaryPipeline"]
