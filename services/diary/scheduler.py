"""日记调度循环。

每天 ``generate_time``（默认 04:00）触发生成，``push_time``（默认 08:00）
触发 ntfy 推送。启动时若发现上次错过，会补跑对应的动作。

- 生成：从消息上下文拉数据 → LLM → 落盘 JSON / Markdown
- 推送：从 storage 读"昨天"的日记 → 调 NtfyNotifier 推送
- 重试：**软失败**（LLM 返回空 / 超时 / 异常）按指数退避重试，最多
  ``retry.max_attempts`` 次，成功即停止；「消息数量不足」是**硬失败**
  （时间窗已闭合，重试无意义），不重试。
- 生成 / 推送 / 重试共用一个 asyncio 任务，循环里取较早的下一次触发。
- 防重复（幂等）不依赖 persist_state 开关：
  - 补生成按"昨日日记数据是否存在"判定（报错记录也算存在，但若重试预算
    未耗尽则由 ``retry_state.json`` 驱动续跑）；
  - 推送按双通道标记判定：同一日记日期最多推 1 条正常日记 + 1 条失败消息。
- 重试状态落盘 ``retry_state.json``（先写状态再等退避），进程崩溃/重启后
  由 ``_maybe_recover`` 决定是否续跑剩余次数。
"""

from __future__ import annotations

import asyncio
import datetime
import time
from typing import Any, Dict, Optional, Tuple

from ...utils import get_logger
from ...utils.date import format_date_str, local_now, parse_clock
from .ntfy_notifier import NtfyNotifier
from .pipeline import DiaryPipeline
from .storage import DiaryStorage

logger = get_logger(__name__)

# 会自动进入重试队列的来源；manual（手动 /diary gen）不在列——用户在场，
# 失败直接回报，由用户决定是否再跑。
_AUTO_RETRY_SOURCES = frozenset({"schedule", "recover", "retry"})


class DiaryScheduler:
    """基于 asyncio 的轻量级调度器，同时管理生成、推送与失败重试。"""

    def __init__(self, plugin) -> None:
        self._plugin = plugin
        self._cfg = plugin.config
        self._storage = DiaryStorage(base_dir=self._cfg.output.base_dir)
        self._notifier = NtfyNotifier(self._cfg.ntfy)
        self._is_running = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._last_trigger_ts: float = 0.0
        # 待执行的重试（内存态）：{"date": str, "attempts_done": int, "next_at": datetime}
        self._retry: Optional[Dict[str, Any]] = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    def get_status(self) -> dict:
        """供 /diary status 使用的快照。"""
        now = self._local_now()
        next_gen = self._next_at(now, parse_clock(self._cfg.schedule.generate_time))
        next_push = self._next_at(now, parse_clock(self._cfg.schedule.push_time))
        last_gen = self._storage.read_last_diary_date()
        return {
            "running": self._is_running,
            "generate_time": self._cfg.schedule.generate_time,
            "push_time": self._cfg.schedule.push_time,
            "timezone_offset_hours": self._cfg.schedule.timezone_offset_hours,
            "now": now.strftime("%Y-%m-%d %H:%M:%S"),
            "last_diary_date": last_gen or "无",
            "last_pushed_diary_date": self._storage.read_last_pushed_diary_date() or "无",
            "last_pushed_error_date": self._storage.read_last_pushed_error_date() or "无",
            "retry_state": self._describe_retry(),
            "next_generate_at": next_gen.strftime("%Y-%m-%d %H:%M:%S") if next_gen else "-",
            "next_push_at": next_push.strftime("%Y-%m-%d %H:%M:%S") if next_push else "-",
            "ntfy_configured": self._notifier.is_configured(),
        }

    # ===== 生命周期 =====

    async def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        # 先把落盘的重试状态加载进内存；是否续跑交给 _maybe_recover 判定
        self._load_retry_state()
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

        与定时生成的两点差异：
        - 失败**不**进入自动重试队列（用户在场，可直接再执行）；
        - 成功后若已过 push_time 且该日期尚未推送过日记，立即补推一次
          （与重试成功后的跟进推送同规则；未到 push_time 则交由调度器正常推送）。
        """
        async with self._lock:
            target_date = format_date_str(date) if date else self._yesterday_str()
            ok, result = await self._generate_for_date_safe(target_date, source="manual")
        if ok:
            await self._maybe_followup_push(target_date)
        return ok, result

    async def push_now(self, date: Optional[str] = None) -> Tuple[bool, str]:
        """手动推送指定日期（默认"昨天"）的最新日记到 ntfy。

        与自动推送的区别：**不受每日每通道 ≤1 条的限额拦截**（用户显式意图），
        但成功后写对应通道标记，避免随后的自动推送重复发送。
        """
        if not self._notifier.is_configured():
            return False, "ntfy 未启用或 topic 未配置"

        target_date = format_date_str(date) if date else self._yesterday_str()
        diary = await self._storage.get_diary(target_date)
        if not diary:
            return False, f"{target_date} 没有日记记录，无法推送"

        status = str(diary.get("status") or "")
        if "报错" in status:
            if not self._cfg.ntfy.send_on_failure:
                return False, "失败通知已关闭（ntfy.send_on_failure=false）"
            error_msg = str(diary.get("error_message") or status)
            ok = await self._notifier.send_failure(date=target_date, error=error_msg)
            if ok:
                self._storage.write_last_pushed_error_date(target_date)
            return ok, (
                f"{target_date} 的失败消息已推送"
                if ok
                else f"{target_date} 的失败消息推送失败（ntfy 未送达）"
            )

        ok = await self._notifier.send_diary(
            date=target_date,
            content=str(diary.get("diary_content") or ""),
            word_count=int(diary.get("word_count") or 0),
            weather=str(diary.get("weather") or ""),
        )
        if ok:
            self._storage.write_last_pushed_diary_date(target_date)
        return ok, (
            f"{target_date} 的日记已推送"
            if ok
            else f"{target_date} 的日记推送失败（ntfy 未送达）"
        )

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
                # 待执行的重试（软失败退避链）
                next_retry = self._retry_next_at()

                candidates: list[tuple[str, datetime.datetime]] = []
                if next_gen is not None:
                    candidates.append(("generate", next_gen))
                if next_push is not None:
                    candidates.append(("push", next_push))
                if next_retry is not None:
                    candidates.append(("retry", next_retry))
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
                elif action == "retry":
                    await self._execute_retry()
                else:
                    await self._push_safe(source="schedule")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("scheduler 循环异常: %s", exc, exc_info=True)
                await asyncio.sleep(min(check_interval, 300))

    async def _has_unpushed_yesterday(self) -> bool:
        """是否存在"昨天"日期的、尚未推送的日记（双通道任一未推即算）。

        幂等判定不依赖 persist_state。重试挂起时这里仍可能返回 True，
        真正是否推送由 ``_push_safe`` 内部的顺延判定把关。
        """
        if not self._notifier.is_configured():
            return False
        target_date = self._yesterday_str()
        diary = await self._storage.get_diary(target_date)
        if diary is None:
            return False
        if "报错" in str(diary.get("status") or ""):
            return self._storage.read_last_pushed_error_date() != target_date
        return self._storage.read_last_pushed_diary_date() != target_date

    async def _maybe_recover(
        self,
        gen_cutoff: Optional[Tuple[int, int]],
        push_cutoff: Optional[Tuple[int, int]],
    ) -> None:
        """启动时补跑：续跑未完成的重试 / 补生成 / 补推送。"""
        now = self._local_now()

        # 补生成（或续跑重试）
        if gen_cutoff is not None:
            target_dt = now.replace(
                hour=gen_cutoff[0], minute=gen_cutoff[1], second=0, microsecond=0
            )
            if now >= target_dt:
                target_date = self._yesterday_str()
                if self._resume_retry_if_any(target_date):
                    # 已恢复重试，交给主循环按 next_at 执行
                    pass
                else:
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

    # ===== 生成与重试 =====

    async def _generate_for_date_safe(self, date: str, *, source: str) -> tuple:
        """执行一次生成；软失败且来源属于自动链路时登记退避重试。

        Returns:
            ``(ok, message)``。
        """
        try:
            pipeline = DiaryPipeline(self._plugin)
            ok, result, retryable = await pipeline.generate_for_date(date)
        except Exception as exc:
            logger.error("[%s] 生成 %s 异常: %s", source, date, exc, exc_info=True)
            ok, result, retryable = False, f"异常: {exc}", True

        if ok:
            logger.info(
                "[%s] %s 日记生成成功（%d 字）",
                source, date, len(result),
            )
            return ok, result

        logger.warning("[%s] %s 日记生成失败: %s", source, date, result)
        if retryable:
            self._maybe_schedule_retry(date, source)
        else:
            logger.info("[%s] %s 判定为硬失败（不可重试），不登记重试", source, date)
        return ok, result

    def _maybe_schedule_retry(self, date: str, source: str) -> None:
        """首次软失败时登记退避重试；后续次数由 ``_execute_retry`` 自行推进。"""
        if source not in _AUTO_RETRY_SOURCES:
            logger.info("[%s] %s 手动触发失败不进入重试队列", source, date)
            return
        if not self._retry_eligible():
            return
        if self._retry_pending_for(date):
            # 已在重试链路中，次数推进由 _execute_retry 负责
            return
        next_at = self._local_now() + datetime.timedelta(seconds=self._retry_delay_seconds(0))
        self._schedule_retry(date, 0, next_at)
        logger.info(
            "[%s] %s 已登记退避重试：第 1/%d 次在 %s",
            source, date, self._max_retry_attempts(), next_at.strftime("%H:%M:%S"),
        )

    async def _execute_retry(self) -> None:
        """执行一次待重试（主循环在 ``next_at`` 到点后调用）。"""
        state = self._retry
        if state is None:
            return
        date = str(state.get("date") or "")
        if not date:
            self._clear_retry("状态缺少日期")
            return
        attempts_done = int(state.get("attempts_done") or 0)

        # 该日期可能已被其它路径修复（如手动 /diary gen 成功）→ 无需再重试
        existing = await self._storage.get_diary(date)
        if existing is not None and "报错" not in str(existing.get("status") or ""):
            logger.info("[retry] %s 已有成功记录，取消剩余重试", date)
            self._clear_retry("已被成功记录覆盖")
            await self._maybe_followup_push(date)
            return

        logger.info(
            "[retry] 第 %d/%d 次重试 %s 的日记",
            attempts_done + 1, self._max_retry_attempts(), date,
        )
        ok, result = await self._generate_for_date_safe(date, source="retry")
        if ok:
            self._clear_retry(f"{date} 重试成功")
            await self._maybe_followup_push(date)
            return

        attempts_done += 1
        if attempts_done >= self._max_retry_attempts():
            logger.warning(
                "[retry] %s 重试预算耗尽（共 %d 次重试），放弃: %s",
                date, attempts_done, result,
            )
            self._clear_retry("预算耗尽")
            # 预算耗尽 = 最终失败；若已过 push_time，尽快把失败消息送达
            await self._maybe_followup_push(date)
            return

        next_at = self._local_now() + datetime.timedelta(
            seconds=self._retry_delay_seconds(attempts_done)
        )
        self._schedule_retry(date, attempts_done, next_at)
        logger.info(
            "[retry] %s 将在 %s 进行第 %d/%d 次重试",
            date, next_at.strftime("%H:%M:%S"),
            attempts_done + 1, self._max_retry_attempts(),
        )

    async def _maybe_followup_push(self, date: str) -> None:
        """重试/手动生成成功（或重试预算耗尽）后的跟进补推。

        仅当目标日期仍是"昨天"、且已过 push_time 时才补推；每通道 ≤1 条由
        ``_push_safe`` 内部把关。若尚未到 push_time，则交由调度器在
        push_time 正常推送，避免一天内多次打扰。
        """
        if date != self._yesterday_str():
            logger.info("[followup] %s 已不是昨天，跳过跟进推送（可 /diary push 手动推）", date)
            return
        push_cutoff = parse_clock(self._cfg.schedule.push_time)
        if push_cutoff is None:
            return
        now = self._local_now()
        target_dt = now.replace(
            hour=push_cutoff[0], minute=push_cutoff[1], second=0, microsecond=0
        )
        if now < target_dt:
            logger.info(
                "[followup] 尚未到 push_time(%s)，交由调度器正常推送",
                self._cfg.schedule.push_time,
            )
            return
        logger.info("[followup] 立即补推 %s 的最新状态（重试链路已终结）", date)
        await self._push_safe(source="followup")

    # ===== 重试状态 =====

    def _load_retry_state(self) -> None:
        """从落盘加载重试状态（是否续跑由 ``_maybe_recover`` 判定）。

        ``next_retry_ts`` 按"剩余秒数"折算成配置时区墙钟：``local_now()``
        在部分环境返回偏移后的墙钟，直接换算时间戳会错位，故只信相对量。
        """
        raw = self._storage.read_retry_state()
        if not raw:
            return
        try:
            attempts_done = int(raw.get("attempts_done") or 0)
            remaining = float(raw.get("next_retry_ts") or 0) - time.time()
        except (TypeError, ValueError):
            logger.warning("retry_state 字段非法，丢弃: %s", raw)
            self._storage.clear_retry_state()
            return
        remaining = max(0.0, remaining)
        self._retry = {
            "date": str(raw.get("date") or ""),
            "attempts_done": attempts_done,
            "next_at": self._local_now() + datetime.timedelta(seconds=remaining),
        }
        logger.info(
            "scheduler: 已加载重试状态 date=%s attempts_done=%d（%.0f 秒后重试）",
            self._retry["date"], attempts_done, remaining,
        )

    def _resume_retry_if_any(self, target_date: str) -> bool:
        """重启时处理落盘的重试状态，返回是否保留续跑。

        - 状态属于目标日期且预算未耗尽 → 保留（主循环按 next_at 执行）；
        - 其余（日期不符 / 预算耗尽）→ 清除并交回常规补生成判定。
        """
        state = self._retry
        if state is None:
            return False
        date = str(state.get("date") or "")
        if date != target_date:
            logger.warning(
                "scheduler: 丢弃过期重试状态（date=%s，当前目标=%s）", date, target_date
            )
            self._clear_retry("重启时日期不匹配")
            return False
        if not self._retry_has_budget(state):
            logger.warning(
                "scheduler: %s 重试预算已耗尽（已试 %d/%d），不再恢复",
                date, int(state.get("attempts_done") or 0), self._max_retry_attempts(),
            )
            self._clear_retry("重启时预算已耗尽")
            return False
        logger.info(
            "scheduler: 恢复 %s 未完成的重试（已试 %d/%d，下次 %s）",
            date, int(state.get("attempts_done") or 0), self._max_retry_attempts(),
            state["next_at"].strftime("%H:%M:%S"),
        )
        return True

    def _retry_next_at(self) -> Optional[datetime.datetime]:
        """待执行重试的下一次触发时间；状态非法时自愈清除并返回 None。"""
        if self._retry is None:
            return None
        next_at = self._retry.get("next_at")
        if not isinstance(next_at, datetime.datetime):
            logger.warning("[retry] 状态缺少合法 next_at，清除: %s", self._retry)
            self._clear_retry("next_at 非法")
            return None
        return next_at

    def _schedule_retry(
        self,
        date: str,
        attempts_done: int,
        next_at: datetime.datetime,
    ) -> None:
        """登记/更新待执行重试，并立即落盘（先写状态再等退避，崩溃可续）。"""
        self._retry = {"date": date, "attempts_done": attempts_done, "next_at": next_at}
        remaining = max(0.0, (next_at - self._local_now()).total_seconds())
        self._storage.write_retry_state(
            date=date,
            attempts_done=attempts_done,
            next_retry_ts=time.time() + remaining,
        )

    def _clear_retry(self, reason: str) -> None:
        """清除重试状态（内存 + 落盘）。"""
        state = self._retry
        if state is not None:
            logger.info(
                "[retry] 清除重试状态（%s）: date=%s 已试 %d/%d",
                reason, state.get("date"),
                int(state.get("attempts_done") or 0), self._max_retry_attempts(),
            )
        self._retry = None
        self._storage.clear_retry_state()

    def _retry_pending_for(self, date: str) -> bool:
        """该日期是否有待执行的重试。"""
        return self._retry is not None and str(self._retry.get("date") or "") == date

    def _retry_has_budget(self, state: Dict[str, Any]) -> bool:
        """重试预算是否尚未耗尽。"""
        return int(state.get("attempts_done") or 0) < self._max_retry_attempts()

    def _retry_eligible(self) -> bool:
        """重试功能是否可用（开关开启且预算 > 0）。"""
        return bool(self._cfg.retry.enabled) and self._max_retry_attempts() > 0

    def _max_retry_attempts(self) -> int:
        """重试次数上限（不含首次尝试）。"""
        return max(0, int(self._cfg.retry.max_attempts or 0))

    def _retry_delay_seconds(self, attempts_done: int) -> float:
        """下一次重试前的退避秒数：base × 2^attempts_done，受 max 封顶。"""
        base = max(1, int(self._cfg.retry.base_delay_minutes or 10)) * 60
        cap = max(base, int(self._cfg.retry.max_delay_minutes or 120) * 60)
        return float(min(base * (2 ** max(0, attempts_done)), cap))

    def _describe_retry(self) -> str:
        """重试状态的可读描述（供 /diary status）。"""
        state = self._retry
        if state is None:
            return "无"
        next_at = state.get("next_at")
        next_text = (
            next_at.strftime("%H:%M:%S") if isinstance(next_at, datetime.datetime) else "-"
        )
        return (
            f"{state.get('date')} 已试 {int(state.get('attempts_done') or 0)}"
            f"/{self._max_retry_attempts()}，下次 {next_text}"
        )

    # ===== 推送 =====

    async def _push_safe(self, *, source: str) -> None:
        """推送动作：从 storage 读"昨天"的日记并推 ntfy。

        限额语义（双通道）：同一日记日期最多推 1 条正常日记 + 1 条失败消息，
        两通道独立计数——先推失败提醒、手动重生成成功后再推日记，各一次。
        """
        if not self._notifier.is_configured():
            logger.info("[%s] ntfy 未启用或 topic 未配置，跳过推送", source)
            return

        target_date = self._yesterday_str()

        # 重试挂起时顺延：此刻的失败消息可能马上被重试成功推翻，先不打扰
        if self._retry_pending_for(target_date):
            logger.info(
                "[%s] %s 重试进行中（%s），本次推送顺延至重试终结",
                source, target_date, self._describe_retry(),
            )
            return

        diary = await self._storage.get_diary(target_date)
        if not diary:
            logger.info(
                "[%s] 没有 %s 的日记可推送（生成被跳过或未生成）",
                source, target_date,
            )
            return

        status = str(diary.get("status") or "")
        if "报错" in status:
            if not self._cfg.ntfy.send_on_failure:
                logger.info(
                    "[%s] %s 为报错记录，但 send_on_failure=false，跳过失败通知",
                    source, target_date,
                )
                return
            if self._storage.read_last_pushed_error_date() == target_date:
                logger.info("[%s] %s 失败消息已推送过，跳过", source, target_date)
                return
            error_msg = str(diary.get("error_message") or status)
            ok = await self._notifier.send_failure(date=target_date, error=error_msg)
            if ok:
                self._storage.write_last_pushed_error_date(target_date)
            else:
                logger.warning(
                    "[%s] %s 失败消息未送达，未更新状态（可 /diary push 手动重试）",
                    source, target_date,
                )
            return

        if self._storage.read_last_pushed_diary_date() == target_date:
            logger.info("[%s] %s 日记已推送过，跳过", source, target_date)
            return
        ok = await self._notifier.send_diary(
            date=target_date,
            content=str(diary.get("diary_content") or ""),
            word_count=int(diary.get("word_count") or 0),
            weather=str(diary.get("weather") or ""),
        )
        if ok:
            self._storage.write_last_pushed_diary_date(target_date)
        else:
            logger.warning(
                "[%s] %s 日记未送达，未更新状态（可 /diary push 手动重试）",
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
