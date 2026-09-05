"""日记调度循环。

每天 ``generate_time``（默认 04:00）触发生成，``push_time``（默认 08:00）
触发 ntfy 推送。启动时若发现上次错过，会补跑对应的动作。

- 生成：从消息上下文拉数据 → LLM → 落盘 JSON / Markdown
- 推送：从 storage 读"昨天"的日记 → 调 NtfyNotifier 推送
- 两个时间点共用一个 asyncio 任务，循环里取较早的下一次触发。
- 防重复（幂等）不依赖 persist_state 开关：补生成按"昨日日记数据是否存在"
  判定，推送按 last_pushed_date 读写判定（修复重启后重复生成/重复推送）。
"""

from __future__ import annotations

import asyncio
import datetime
import time
from typing import Optional, Tuple

from ...utils import get_logger
from ...utils.date import format_date_str, local_now, parse_clock
from .ntfy_notifier import NtfyNotifier
from .pipeline import DiaryPipeline
from .storage import DiaryStorage

logger = get_logger(__name__)


class DiaryScheduler:
    """基于 asyncio 的轻量级调度器，同时管理生成与推送。"""

    def __init__(self, plugin) -> None:
        self._plugin = plugin
        self._cfg = plugin.config
        self._storage = DiaryStorage(base_dir=self._cfg.output.base_dir)
        self._notifier = NtfyNotifier(self._cfg.ntfy)
        self._is_running = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._last_trigger_ts: float = 0.0

    @property
    def is_running(self) -> bool:
        return self._is_running

    def get_status(self) -> dict:
        """供 /diary status 使用的快照。"""
        now = self._local_now()
        next_gen = self._next_at(now, parse_clock(self._cfg.schedule.generate_time))
        next_push = self._next_at(now, parse_clock(self._cfg.schedule.push_time))
        last_gen = self._storage.read_last_diary_date()
        last_push = self._storage.read_last_pushed_date()
        return {
            "running": self._is_running,
            "generate_time": self._cfg.schedule.generate_time,
            "push_time": self._cfg.schedule.push_time,
            "timezone_offset_hours": self._cfg.schedule.timezone_offset_hours,
            "now": now.strftime("%Y-%m-%d %H:%M:%S"),
            "last_diary_date": last_gen or "无",
            "last_pushed_date": last_push or "无",
            "next_generate_at": next_gen.strftime("%Y-%m-%d %H:%M:%S") if next_gen else "-",
            "next_push_at": next_push.strftime("%Y-%m-%d %H:%M:%S") if next_push else "-",
            "ntfy_configured": self._notifier.is_configured(),
        }

    # ===== 生命周期 =====

    async def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self._task = asyncio.create_task(self._loop(), name="mai-diary-scheduler")
        logger.info("mai-diary scheduler 已启动")

    async def stop(self) -> None:
        if not self._is_running:
            return
        self._is_running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("mai-diary scheduler 已停止")

    async def trigger_now(self, date: Optional[str] = None) -> tuple:
        """手动触发生成。``date`` 为空时取配置的时区下的"昨天"。

        注意：手动触发的生成**不会**立即推送，会在下一次 push_time 由
        调度器统一推送（避免一天内多次打扰）。
        """
        async with self._lock:
            target_date = format_date_str(date) if date else self._yesterday_str()
            return await self._generate_for_date_safe(target_date, source="manual")

    # ===== 主循环 =====

    async def _loop(self) -> None:
        check_interval = max(5, int(self._cfg.schedule.check_interval_seconds or 60))

        gen_cutoff = parse_clock(self._cfg.schedule.generate_time)
        push_cutoff = parse_clock(self._cfg.schedule.push_time)
        if gen_cutoff is None:
            logger.error("schedule.generate_time 格式错误，调度器退出")
            return
        if push_cutoff is None:
            logger.warning(
                "schedule.push_time 格式错误（%s），推送将永不触发",
                self._cfg.schedule.push_time,
            )

        # 启动补跑
        try:
            await self._maybe_recover(gen_cutoff, push_cutoff)
        except Exception as exc:
            logger.error("启动补跑异常: %s", exc, exc_info=True)

        while self._is_running:
            try:
                now = self._local_now()
                next_gen = self._next_at(now, gen_cutoff)
                # 仅当存在未推送的"昨天"日记时，推送才进入候选
                next_push: Optional[datetime.datetime] = None
                if push_cutoff is not None and await self._has_unpushed_yesterday():
                    next_push = self._next_at(now, push_cutoff)

                candidates: list[tuple[str, datetime.datetime]] = []
                if next_gen is not None:
                    candidates.append(("generate", next_gen))
                if next_push is not None:
                    candidates.append(("push", next_push))
                if not candidates:
                    await asyncio.sleep(check_interval)
                    continue

                candidates.sort(key=lambda x: x[1])
                action, at = candidates[0]

                wait_seconds = max(1.0, (at - now).total_seconds())
                self._last_trigger_ts = time.time()
                await asyncio.sleep(wait_seconds)
                if not self._is_running:
                    break

                if action == "generate":
                    target_date = self._yesterday_str()
                    await self._generate_for_date_safe(target_date, source="schedule")
                else:
                    await self._push_safe(source="schedule")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("scheduler 循环异常: %s", exc, exc_info=True)
                await asyncio.sleep(min(check_interval, 300))

    async def _has_unpushed_yesterday(self) -> bool:
        """是否存在"昨天"日期的、未推送的日记。"""
        if not self._notifier.is_configured():
            return False
        target_date = self._yesterday_str()
        # 幂等判定不依赖 persist_state：已推送过昨天就直接返回 False
        if self._storage.read_last_pushed_date() == target_date:
            return False
        return await self._storage.get_diary(target_date) is not None

    async def _maybe_recover(
        self,
        gen_cutoff: Optional[Tuple[int, int]],
        push_cutoff: Optional[Tuple[int, int]],
    ) -> None:
        """启动时补跑：若已过 trigger 时间且对应动作未发生。"""
        now = self._local_now()

        # 补生成
        if gen_cutoff is not None:
            target_dt = now.replace(
                hour=gen_cutoff[0], minute=gen_cutoff[1], second=0, microsecond=0
            )
            if now >= target_dt:
                target_date = self._yesterday_str()
                # 按数据存在性判定：昨日已有日记数据（无论成功或报错状态）
                # 就不重生成，避免重启后重复生成；数据缺失才补跑。
                existing = await self._storage.get_diary(target_date)
                if existing is None:
                    logger.info("scheduler: 启动补生成 %s 的日记", target_date)
                    await self._generate_for_date_safe(target_date, source="recover")
                else:
                    logger.info(
                        "scheduler: %s 的日记已存在（status=%s），跳过补生成",
                        target_date, str(existing.get("status") or ""),
                    )

        # 补推送
        if push_cutoff is not None:
            target_dt = now.replace(
                hour=push_cutoff[0], minute=push_cutoff[1], second=0, microsecond=0
            )
            if now >= target_dt:
                await self._push_safe(source="recover")

    async def _generate_for_date_safe(self, date: str, *, source: str) -> tuple:
        try:
            pipeline = DiaryPipeline(self._plugin)
            ok, result = await pipeline.generate_for_date(date)
        except Exception as exc:
            logger.error("[%s] 生成 %s 异常: %s", source, date, exc, exc_info=True)
            return False, f"异常: {exc}"

        if ok:
            logger.info(
                "[%s] %s 日记生成成功（%d 字）",
                source, date, len(result),
            )
        else:
            logger.warning("[%s] %s 日记生成失败: %s", source, date, result)
        return ok, result

    async def _push_safe(self, *, source: str) -> None:
        """推送动作：从 storage 读"昨天"的日记并推 ntfy。"""
        if not self._notifier.is_configured():
            logger.info("[%s] ntfy 未启用或 topic 未配置，跳过推送", source)
            return

        target_date = self._yesterday_str()

        # 幂等判定不依赖 persist_state：推送过的日期不再重复推送
        last_pushed = self._storage.read_last_pushed_date()
        if last_pushed == target_date:
            logger.info("[%s] %s 今日已推送，跳过", source, target_date)
            return

        diary = await self._storage.get_diary(target_date)
        if not diary:
            logger.info(
                "[%s] 没有 %s 的日记可推送（生成被跳过或未生成）",
                source, target_date,
            )
            return

        status = str(diary.get("status") or "")
        word_count = int(diary.get("word_count") or 0)
        weather = str(diary.get("weather") or "")
        content = str(diary.get("diary_content") or "")

        if "报错" in status:
            error_msg = str(diary.get("error_message") or status)
            ok = await self._notifier.send_failure(date=target_date, error=error_msg)
        else:
            ok = await self._notifier.send_diary(
                date=target_date,
                content=content,
                word_count=word_count,
                weather=weather,
            )

        if ok:
            # 幂等状态始终落盘（不受 persist_state 门控），否则重启后无法判定"已推送"
            self._storage.write_last_pushed_date(target_date)
        elif not ok:
            logger.warning(
                "[%s] %s ntfy 推送未送达，未更新 last_pushed_date，下次重试",
                source, target_date,
            )

    # ===== 时间计算 =====

    def _yesterday_str(self) -> str:
        """配置时区下的"昨天"（YYYY-MM-DD）。"""
        return (self._local_now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    def _local_now(self) -> datetime.datetime:
        """按配置时区取本地时间（系统时区感知，规避 UTC mislabel 错位）。"""
        return local_now(int(self._cfg.schedule.timezone_offset_hours or 0))

    @staticmethod
    def _next_at(
        now: datetime.datetime,
        cutoff: Optional[Tuple[int, int]],
    ) -> Optional[datetime.datetime]:
        """下一个 ``HH:MM`` 时刻（严格未来，含 today）。"""
        if cutoff is None:
            return None
        target = now.replace(hour=cutoff[0], minute=cutoff[1], second=0, microsecond=0)
        if target <= now:
            target = target + datetime.timedelta(days=1)
        return target


__all__ = ["DiaryScheduler"]
