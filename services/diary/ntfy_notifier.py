"""ntfy 推送器。

通过 ntfy.sh 或自建 ntfy 服务 HTTP POST 推送日记通知。
所有异常均被吞掉只记 warn 日志——绝不能影响日记生成 / 推送主流程。

实现说明：使用 stdlib ``http.client`` + 自定义 ``putheader`` 旁路，
因为 ``urllib.request`` / ``http.client`` 默认把 header value 用 latin-1 编码，
无法发送中文 / emoji。

边界约束：仅由 DiaryScheduler 在 push_time 触发时调用；不做内容缓存。
"""

from __future__ import annotations

import asyncio
import http.client
import socket
import ssl
from typing import TYPE_CHECKING, List, Optional, Tuple
from urllib.parse import quote, urlparse

from ...utils import get_logger
from ...utils.tokens import smart_truncate

if TYPE_CHECKING:
    from ...config import NtfySection

logger = get_logger(__name__)


_DEFAULT_TIMEOUT = 10
_NTFY_SUCCESS_STATUS = {200, 201, 202}


class _Utf8HTTPSConnection(http.client.HTTPSConnection):
    """``http.client.HTTPSConnection`` 子类，旁路 ``putheader`` 的 latin-1 编码。

    Python 的 ``http.client.HTTPConnection.putheader`` 会对每个 header value
    调用 ``.encode('latin-1')``，遇到中文 / emoji 会抛 ``UnicodeEncodeError``。
    这里把 str value 提前编码成 UTF-8 字节再写入。

    **Python 3.14 行为变更**：3.14 把 ``putheader`` 改为只写 ``Name: Value``
    （**不带** ``\\r\\n``），由 ``_send_output`` 通过 ``b"\\r\\n".join(buffer)``
    统一加 ``\\r\\n``。所以这里也不能加 ``\\r\\n``，否则会多出空行。
    """

    def putheader(self, header, *values):  # type: ignore[override]
        if hasattr(header, "encode"):
            header = header.encode("ascii")
        if not values:
            return
        for one_value in values:
            if isinstance(one_value, str):
                one_value = one_value.encode("utf-8")
            # 注意：3.14 下不加 \r\n；3.12 及以下 _send_output 同样负责加 \r\n
            self._output(header + b": " + one_value)


class _Utf8HTTPConnection(http.client.HTTPConnection):
    """明文 HTTP 版本的旁路（自建 ntfy 可能用 http://）。"""

    def putheader(self, header, *values):  # type: ignore[override]
        if hasattr(header, "encode"):
            header = header.encode("ascii")
        if not values:
            return
        for one_value in values:
            if isinstance(one_value, str):
                one_value = one_value.encode("utf-8")
            self._output(header + b": " + one_value)


class NtfyNotifier:
    """ntfy 推送封装。

    Args:
        cfg: NtfySection 配置对象。
    """

    def __init__(self, cfg: "NtfySection") -> None:
        self._cfg = cfg
        self._server = (cfg.server or "https://ntfy.sh").rstrip("/")
        self._topic = (cfg.topic or "").strip()
        self._timeout = max(1, int(cfg.timeout_seconds or _DEFAULT_TIMEOUT))

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def server(self) -> str:
        return self._server

    def is_configured(self) -> bool:
        """是否已正确配置（enabled=True 且 topic 非空）。"""
        return bool(self._cfg.enabled and self._topic)

    async def send_diary(
        self,
        *,
        date: str,
        content: str,
        word_count: int,
        weather: str = "",
    ) -> bool:
        """成功日记推送。返回是否真正送达。"""
        if not self.is_configured():
            return False

        try:
            title = self._cfg.title_template.format(
                date=date, word_count=word_count, weather=weather,
            )
        except Exception as exc:
            logger.warning("ntfy 标题模板渲染失败: %s", exc)
            title = f"新日记  {date}"

        body = self._build_body(content, word_count)

        return await self._post(
            title=title,
            body=body,
            priority=self._cfg.priority or "default",
            tags=list(self._cfg.tags or []),
            click=(self._cfg.click_action or "").strip() or None,
        )

    async def send_failure(
        self,
        *,
        date: str,
        error: str,
    ) -> bool:
        """失败通知。返回是否真正送达。"""
        if not self.is_configured():
            return False
        if not self._cfg.send_on_failure:
            return False

        try:
            title = self._cfg.failure_title_template.format(
                date=date, error=error,
            )
        except Exception as exc:
            logger.warning("ntfy 失败标题模板渲染失败: %s", exc)
            title = f"❌ 日记生成失败  {date}"

        body = self._limit_body(
            f"日记生成失败：{error}\n\n"
            f"可执行 /diary gen {date} 手动重试。\n\n"
            "—— mai-diary"
        )

        return await self._post(
            title=title,
            body=body,
            priority=self._cfg.priority or "default",
            tags=list(self._cfg.tags or []),
            click=(self._cfg.click_action or "").strip() or None,
        )

    def _limit_body(self, text: str) -> str:
        """按 ``max_body_chars`` 截断。

        失败通知原本**没有**长度约束 —— 2026-09-15 起 error 换成了真实 API 报错
        （可能带大段文本 / 堆栈），不截断会超过公共 ntfy.sh 约 4KB 的 body 上限
        而被 413 拒收，连失败通知都收不到。
        """
        max_chars = max(50, int(self._cfg.max_body_chars or 2000))
        if len(text) <= max_chars:
            return text
        return (
            smart_truncate(text, max_chars)
            + "\n\n…（已截断，完整报错见 data/diary/errors/）"
        )

    def _build_body(self, content: str, word_count: int) -> str:
        body = content or ""
        max_chars = max(50, int(self._cfg.max_body_chars or 2000))
        if len(body) > max_chars:
            body = smart_truncate(body, max_chars)
            suffix = self._cfg.truncate_suffix or "\n\n…（已截断，全文见本地文件）"
            body = body + suffix

        footer_tpl = self._cfg.body_footer_template or ""
        if footer_tpl:
            try:
                body = body + footer_tpl.format(word_count=word_count)
            except Exception as exc:
                logger.warning("ntfy 尾巴模板渲染失败: %s", exc)
                body = body + footer_tpl

        return body

    async def _post(
        self,
        *,
        title: str,
        body: str,
        priority: str,
        tags: List[str],
        click: Optional[str],
    ) -> bool:
        try:
            host, port, use_https, path = self._parse_server()
        except ValueError as exc:
            logger.warning("ntfy 服务器 URL 解析失败: %s, topic=%s", exc, self._topic)
            return False

        headers: List[Tuple[str, str]] = [
            ("Title", title),
            ("Priority", priority),
            ("Tags", ",".join(tags) if tags else ""),
        ]
        if click:
            headers.append(("Click", click))
        auth_token = (self._cfg.auth_token or "").strip()
        if auth_token:
            headers.append(("Authorization", f"Bearer {auth_token}"))

        data = body.encode("utf-8")

        def _do_request() -> int:
            conn_cls = _Utf8HTTPSConnection if use_https else _Utf8HTTPConnection
            conn = conn_cls(host, port, timeout=self._timeout)
            try:
                conn.request("POST", path, body=data, headers=dict(headers))
                resp = conn.getresponse()
                status = resp.status
                # 读到 body 以维持连接干净
                _ = resp.read()
                return status
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        try:
            status = await asyncio.to_thread(_do_request)
        except (socket.gaierror, ConnectionError, TimeoutError, OSError) as exc:
            logger.warning("ntfy 推送网络异常: %s, topic=%s", exc, self._topic)
            return False
        except ssl.SSLError as exc:
            logger.warning("ntfy 推送 SSL 异常: %s, topic=%s", exc, self._topic)
            return False
        except http.client.HTTPException as exc:
            logger.warning("ntfy 推送 HTTP 异常: %s, topic=%s", exc, self._topic)
            return False
        except Exception as exc:
            logger.warning("ntfy 推送未分类异常: %s, topic=%s", exc, self._topic)
            return False

        if status in _NTFY_SUCCESS_STATUS:
            logger.info("ntfy 推送成功: status=%d, topic=%s", status, self._topic)
            return True
        if status == 413:
            logger.warning(
                "ntfy 推送被服务端拒绝 (413 Payload Too Large)，"
                "请调小 [ntfy].max_body_chars 后重试。topic=%s",
                self._topic,
            )
            return False
        logger.warning(
            "ntfy 推送返回非预期状态: %d, topic=%s", status, self._topic,
        )
        return False

    def _parse_server(self) -> Tuple[str, int, bool, str]:
        """解析 server URL，返回 (host, port, use_https, path)。"""
        parsed = urlparse(self._server)
        scheme = (parsed.scheme or "https").lower()
        if scheme not in ("http", "https"):
            raise ValueError(f"不支持的 scheme: {scheme}")
        host = parsed.hostname or ""
        if not host:
            raise ValueError(f"无法解析 host: {self._server}")
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        # topic 拼到 path 后
        if not path.endswith("/"):
            path = path + "/"
        path = path + quote(self._topic, safe="")
        return host, port, scheme == "https", path


__all__ = ["NtfyNotifier"]
