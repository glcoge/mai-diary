"""mai-diary 插件入口。

业务逻辑全部抽到 services/，入口只负责：装配生命周期、声明命令 / API。

边界约束：日记正文**只**以本地文件形式留存，**不**通过任何命令 / Tool / API
回传。若需阅读，请直接打开 ``data/diary/markdown/YYYY-MM-DD.md``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Optional

import contextlib
import json

from maibot_sdk import API, Command, MaiBotPlugin, PluginConfigBase

from .config import MaiDiaryPluginConfig
from .utils import get_logger

logger = get_logger(__name__)


def _manifest_version(log: Any, manifest_path: Optional[Path] = None) -> str:
    """从插件自带的 _manifest.json 读版本号。

    背景（2026-09-14 踩坑）：加载日志曾把版本号写死成一个常量字符串（与 manifest
    无关），传旧版本的 config.py 也会打印同样的文案，导致**每次部署都无法用日志
    确认远端是否真的更新了**。故改读 manifest，与 narrative 侧口径一致；读取失败
    一律返回"未知"并告警，不静默降级成某种看起来正常的固定版本。
    """
    path = manifest_path or (Path(__file__).parent / "_manifest.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        version = str(data.get("version") or "").strip()
    except (OSError, ValueError) as exc:
        log.warning("读取 _manifest.json 版本失败: %s", exc)
        return "未知"
    if not version:
        log.warning("_manifest.json 缺少 version 字段")
        return "未知"
    return version


class MaiDiaryPlugin(MaiBotPlugin):
    """mai-diary：每天 04:00 自动总结昨日聊天，生成 Markdown + JSON 本地日记。

    所有命令 / API **只**返回元信息（日期 / 字数 / 状态 / 文件路径），
    不返回日记正文。要阅读日记，请直接读 ``data/diary/markdown/YYYY-MM-DD.md``。
    """

    config_model: ClassVar[type[PluginConfigBase] | None] = MaiDiaryPluginConfig

    _scheduler: Optional[Any]

    def __init__(self) -> None:
        super().__init__()
        self._scheduler = None

    # ===== 生命周期 =====

    async def on_load(self) -> None:
        self._warn_removed_config_keys()
        if not self.config.plugin.enabled:
            self.ctx.logger.info("mai-diary 已禁用（plugin.enabled=false）")
            return

        from .services.diary.scheduler import DiaryScheduler
        self._scheduler = DiaryScheduler(self)
        await self._scheduler.start()
        ntfy = self.config.ntfy
        ntfy_state = (
            f"已启用(topic={ntfy.topic}, server={ntfy.server})"
            if ntfy.enabled and ntfy.topic
            else "未启用"
        )
        self.ctx.logger.info(
            "mai-diary v%s 已加载（generate_time=%s, push_time=%s, "
            "base_dir=%s, ntfy=%s）",
            _manifest_version(self.ctx.logger),
            self.config.schedule.generate_time,
            self.config.schedule.push_time,
            self.config.output.base_dir,
            ntfy_state,
        )

    def _warn_removed_config_keys(self) -> None:
        """探测已移除的配置键并告警（SDK ``extra="ignore"`` 会静默丢弃，用户无感知）。

        背景（2026-09-16）：``[output].write_json`` 全仓从未被读取，JSON 始终写入，
        残留该键会让用户以为"关掉能省盘"。
        """
        try:
            raw_config = self.get_plugin_config_data()
        except Exception as exc:
            self.ctx.logger.debug("读取原始配置数据失败（跳过移除键检查）: %s", exc)
            return
        output_raw = raw_config.get("output")
        if isinstance(output_raw, dict) and "write_json" in output_raw:
            self.ctx.logger.warning(
                "检测到已移除的配置键 [output].write_json（该字段从未被读取，JSON 始终写入；"
                "/diary ls 与 /diary v 依赖它）。残留值不再生效，可从 config.toml 删除。"
            )

    async def on_unload(self) -> None:
        if self._scheduler is not None:
            with contextlib.suppress(Exception):
                await self._scheduler.stop()
        self._scheduler = None
        self.ctx.logger.info("mai-diary 已卸载")

    async def on_config_update(
        self,
        scope: str,
        config_data: dict,
        version: str,
    ) -> None:
        """配置热重载。运行时参数由 services 在调用时实时读取，无需重启。"""
        del config_data
        self.ctx.logger.info(
            "mai-diary 配置更新: scope=%s version=%s", scope, version
        )

    # ===== 内部 =====

    def _is_admin(self, user_id: str) -> bool:
        admin_list = list(self.config.plugin.admin_qq or [])
        if not admin_list:
            return False
        return str(user_id) in {str(x) for x in admin_list}

    def _md_path(self, date: str) -> str:
        base = self.config.output.base_dir
        return f"{base}/markdown/{date}.md"

    def _json_path(self, date: str) -> str:
        """最新一份 JSON 的路径（精确文件名未知，返回通配形式便于人读）。"""
        base = self.config.output.base_dir
        return f"{base}/json/{date}_*.json"

    async def _cmd_help(self, stream_id: str) -> None:
        text = (
            "/diary help                  - 查看本帮助\n"
            "/diary gen [日期]            - 手动触发生成（默认昨天）\n"
            "/diary push [日期]           - 手动推送该日日记到 ntfy（默认昨天）\n"
            "/diary ls                    - 列出最近 10 篇日记\n"
            "/diary v [日期] [编号]       - 查看某天日记的元信息 + 文件路径\n"
            "/diary status                - 调度器与最近一次生成状态\n"
            "日期支持: YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD / 今天 / 昨天 / 前天\n"
            "说明: 日记正文**不会**通过命令回传，请直接打开 markdown 文件查看。"
        )
        await self.ctx.send.text(text, stream_id)

    async def _cmd_gen(self, param: str, stream_id: str) -> None:
        from .utils.date import format_date_str, parse_date, yesterday_str
        date = format_date_str(parse_date(param)) if param else yesterday_str()
        if not date:
            await self.ctx.send.text(f"日期格式错误: {param}", stream_id)
            return
        await self.ctx.send.text(f"正在生成 {date} 的日记...", stream_id)
        ok, result = await self._scheduler.trigger_now(date)
        if not ok:
            await self.ctx.send.text(f"生成失败: {result}", stream_id)
            return
        await self._send_diary_meta(stream_id, date, word_count=len(result))

    async def _send_diary_meta(
        self,
        stream_id: str,
        date: str,
        *,
        word_count: int,
    ) -> None:
        """统一回复：元信息 + 文件路径（不含任何日记正文）。"""
        md = self._md_path(date)
        js = self._json_path(date)
        text = (
            f"{date} 日记已生成\n"
            f"  字数: {word_count}\n"
            f"  Markdown: {md}\n"
            f"  JSON:     {js}\n"
            f"（正文请直接打开上述文件查看，本插件不会回传内容）"
        )
        await self.ctx.send.text(text, stream_id)

    async def _cmd_push(self, param: str, stream_id: str) -> None:
        """手动推送指定日期（默认昨天）的最新日记 / 失败消息到 ntfy。

        与自动推送的区别：不受"每日每通道 ≤1 条"限额拦截（用户显式意图），
        推送成功后仍会写通道状态，避免随后的自动推送重复发送。
        """
        from .utils.date import format_date_str, parse_date, yesterday_str
        date = format_date_str(parse_date(param)) if param else yesterday_str()
        if not date:
            await self.ctx.send.text(f"日期格式错误: {param}", stream_id)
            return
        if self._scheduler is None:
            await self.ctx.send.text("调度器未启动（plugin.enabled=false？）", stream_id)
            return
        await self.ctx.send.text(f"正在推送 {date} 的日记...", stream_id)
        ok, msg = await self._scheduler.push_now(date)
        await self.ctx.send.text(("✅ " if ok else "⚠️ ") + msg, stream_id)

    async def _cmd_ls(self, stream_id: str) -> None:
        from .services.diary.storage import DiaryStorage
        storage = DiaryStorage(base_dir=self.config.output.base_dir)
        stats = await storage.get_stats()
        diaries = await storage.list_diaries(limit=10)
        lines = [
            f"共{stats['total_count']}篇 | 均{stats['avg_words']}字 | 最新{stats['latest_date']}",
            "",
        ]
        if diaries:
            for i, d in enumerate(diaries, 1):
                status = d.get("status", "?")
                lines.append(
                    f"  {i}. {d.get('date', '?')} | {d.get('word_count', 0)}字 | {status} | {self._md_path(d.get('date', '?'))}"
                )
        else:
            lines.append("暂无日记")
        await self.ctx.send.text("\n".join(lines), stream_id)

    async def _cmd_view(self, param: str, stream_id: str) -> None:
        from .services.diary.storage import DiaryStorage
        from .utils.date import format_date_str, parse_date, today_str
        storage = DiaryStorage(base_dir=self.config.output.base_dir)
        parts = param.split() if param else []
        if parts:
            date = parse_date(parts[0])
            if not date:
                await self.ctx.send.text(f"日期格式错误: {parts[0]}", stream_id)
                return
            date = format_date_str(date)
        else:
            date = today_str()

        diaries = await storage.get_diaries_by_date(date)
        if not diaries:
            await self.ctx.send.text(
                f"{date} 没有日记（文件路径: {self._md_path(date)}）",
                stream_id,
            )
            return

        if len(parts) > 1:
            try:
                idx = int(parts[1]) - 1
                if 0 <= idx < len(diaries):
                    d = diaries[idx]
                    await self._send_diary_meta(
                        stream_id,
                        date,
                        word_count=d.get("word_count", 0),
                    )
                    return
                await self.ctx.send.text(
                    f"编号超出范围，共{len(diaries)}条", stream_id
                )
                return
            except ValueError:
                pass

        d = diaries[-1]
        wc = d.get("word_count", 0)
        await self._send_diary_meta(stream_id, date, word_count=wc)
        if len(diaries) > 1:
            await self.ctx.send.text(
                f"（该日共{len(diaries)}条，/diary v {date} <编号> 查看其他条的文件路径）",
                stream_id,
            )

    async def _cmd_status(self, stream_id: str) -> None:
        if self._scheduler is None:
            await self.ctx.send.text("调度器未启动（plugin.enabled=false？）", stream_id)
            return
        s = self._scheduler.get_status()
        ntfy_state = "已配置" if s["ntfy_configured"] else "未配置/未启用"
        text = (
            f"运行中: {s['running']}\n"
            f"生成时间: {s['generate_time']} (UTC{s['timezone_offset_hours']:+d})\n"
            f"推送时间: {s['push_time']}\n"
            f"当前时间: {s['now']}\n"
            f"上次生成: {s['last_diary_date']}\n"
            f"上次推送日记: {s['last_pushed_diary_date']}\n"
            f"上次推送失败: {s['last_pushed_error_date']}\n"
            f"重试状态: {s['retry_state']}\n"
            f"下次生成: {s['next_generate_at']}\n"
            f"下次推送: {s['next_push_at']}\n"
            f"ntfy: {ntfy_state}"
        )
        await self.ctx.send.text(text, stream_id)

    # ===== Command 组件 =====

    @Command(
        "diary",
        description="mai-diary 统一命令：/diary help 查看用法",
        pattern=r"^\s*/diary(?:\s+(?P<sub>.+))?\s*$",
    )
    async def handle_diary(self, **kwargs: Any) -> tuple:
        matched = (kwargs.get("matched_groups") or {}).get("sub") or ""
        stream_id = str(kwargs.get("stream_id", "") or "")
        user_id = str(kwargs.get("user_id", "") or "")

        if not self._is_admin(user_id):
            admin_list = list(self.config.plugin.admin_qq or [])
            msg = "⚠️ 未配置管理员" if not admin_list else "⚠️ 仅管理员可用"
            await self.ctx.send.text(msg, stream_id)
            return False, "no admin", True

        raw = matched.strip()
        # 插件关闭时只保留 help。其余命令都依赖 _scheduler（on_load 早退后为 None），
        # 直接放行会在 _cmd_gen 里抛 AttributeError（2026-09-16 修复）。
        if not self.config.plugin.enabled:
            if not raw or raw == "help":
                await self._cmd_help(stream_id)
            else:
                await self.ctx.send.text(
                    "⚠️ diary 插件已禁用（plugin.enabled=false），仅 /diary help 可用",
                    stream_id,
                )
            return True, "plugin disabled", True

        if not raw or raw == "help":
            await self._cmd_help(stream_id)
            return True, "ok", True

        parts = raw.split(None, 1)
        cmd = parts[0].lower()
        param = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "gen":
            await self._cmd_gen(param, stream_id)
            return True, "ok", True
        if cmd == "push":
            await self._cmd_push(param, stream_id)
            return True, "ok", True
        if cmd == "ls":
            await self._cmd_ls(stream_id)
            return True, "ok", True
        if cmd == "v":
            await self._cmd_view(param, stream_id)
            return True, "ok", True
        if cmd == "status":
            await self._cmd_status(stream_id)
            return True, "ok", True

        await self.ctx.send.text(f"未知子命令: {cmd}\n\n/help 之后可以看 /diary help", stream_id)
        return False, "unknown sub", True

    # ===== API 组件（**只**回元信息，不回日记正文） =====

    @API(
        "generate_diary_api",
        description=(
            "触发指定日期的日记生成。参数：date(str, YYYY-MM-DD，可空，默认昨天)。"
            "返回 {ok, date, word_count, status, file_path_markdown, file_path_json}（**不含** content）。"
        ),
        version="1",
        public=True,
    )
    async def handle_generate_diary_api(self, date: str = "", **kwargs: Any) -> dict:
        del kwargs
        if self._scheduler is None:
            return {"ok": False, "error": "scheduler not started"}
        ok, result = await self._scheduler.trigger_now(date or None)
        if not ok:
            return {"ok": False, "error": result}
        resolved_date = (date or "").strip() or "yesterday"
        return {
            "ok": True,
            "date": resolved_date,
            "word_count": len(result),
            "status": "生成成功",
            "file_path_markdown": self._md_path(resolved_date),
            "file_path_json": self._json_path(resolved_date),
        }


def create_plugin() -> MaiDiaryPlugin:
    """工厂函数：Runner 通过此函数实例化插件。"""
    return MaiDiaryPlugin()
