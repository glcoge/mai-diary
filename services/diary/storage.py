"""日记落盘：JSON + Markdown。

布局（base_dir 默认 ``data/diary``）：

- ``data/diary/json/YYYY-MM-DD_HHMMSS.json``  结构化记录（命令 / Tool / API 读取）
- ``data/diary/markdown/YYYY-MM-DD.md``       本地留存，纯展示（不经任何接口输出）
- ``data/diary_index.json``                    索引
- ``data/diary/last_diary_date.txt``          最近一次生成日期（防重复）
- ``data/diary/last_pushed_diary_date.txt``   最近一次「正常日记」推送日期（防重复推送）
- ``data/diary/last_pushed_error_date.txt``   最近一次「失败消息」推送日期（同上，双通道独立计数）
- ``data/diary/last_pushed_date.txt``         **旧版**单通道推送标记（只读回退，惰性迁移）
- ``data/diary/retry_state.json``             软失败退避重试状态（崩溃后据其续跑）
- ``data/diary/errors/YYYY-MM-DD.log``        生成失败的完整报错（追加，含堆栈与上下文）

推送状态为**双通道**：同一日记日期最多推 1 条正常日记 + 1 条失败消息，互不占用配额。
旧版 ``last_pushed_date.txt`` 不再写入；读取新文件缺失时回退读它（视为两个通道都已推送过
该日期），保证升级当天不重复推送。
"""

from __future__ import annotations

import datetime
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...utils import get_logger
from ...utils.date import format_date_str

logger = get_logger(__name__)


class DiaryStorage:
    """日记存储管理器。

    Args:
        base_dir: 根目录（相对插件目录或绝对路径均可）。
    """

    def __init__(self, base_dir: str = "data/diary") -> None:
        plugin_root = Path(__file__).resolve().parent.parent.parent
        self._base = Path(base_dir)
        if not self._base.is_absolute():
            self._base = plugin_root / self._base
        self.json_dir = self._base / "json"
        self.markdown_dir = self._base / "markdown"
        self.error_dir = self._base / "errors"
        self.index_file = self._base / "diary_index.json"
        self._state_file = self._base / "last_diary_date.txt"
        self._diary_push_state_file = self._base / "last_pushed_diary_date.txt"
        self._error_push_state_file = self._base / "last_pushed_error_date.txt"
        # 旧版单通道标记：仅作惰性迁移回退读取，不再写入
        self._legacy_push_state_file = self._base / "last_pushed_date.txt"
        self._retry_state_file = self._base / "retry_state.json"
        self._base.mkdir(parents=True, exist_ok=True)
        self.json_dir.mkdir(parents=True, exist_ok=True)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)
        self.error_dir.mkdir(parents=True, exist_ok=True)
        self.index_file.parent.mkdir(parents=True, exist_ok=True)

    # ===== 写入 =====

    def append_error_log(self, date: str, detail: str) -> str:
        """把一次失败的**完整**报错追加写入 ``errors/YYYY-MM-DD.log``。

        JSON 里的 ``error_message`` 只留一行短原因（它要推 ntfy、要在命令里显示，
        塞堆栈会撑爆 4KB），完整信息 —— 异常堆栈 + 模型名 / 超时 / prompt 长度等
        排查上下文 —— 单独落到这里。同一天多次失败**追加而非覆盖**，保留重试过程。

        Returns:
            写入的路径；写入失败返回空串（不抛异常，绝不阻塞主流程）。
        """
        path = self.error_dir / f"{format_date_str(date)}.log"
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(f"[{stamp}] {detail.rstrip()}\n")
            return str(path)
        except Exception as exc:
            logger.error("写错误日志失败: %s", exc)
            return ""

    async def save_diary(
        self,
        diary_data: Dict[str, Any],
        *,
        write_markdown: bool = True,
        markdown_header_template: str = "# {date} 日记\n\n",
        markdown_footer_template: str = "\n\n---\n\n*由 mai-diary 插件于 {generated_at} 生成*\n",
    ) -> Dict[str, str]:
        """保存一条日记。

        Returns:
            实际写入的路径 ``{"json": "...", "markdown": "..."}``（未开启的项值为空串）。
        """
        try:
            date = diary_data["date"]
        except KeyError as exc:
            raise ValueError("diary_data 必须包含 'date' 字段") from exc

        generation_time = float(diary_data.get("generation_time") or time.time())
        ts_label = datetime.datetime.fromtimestamp(generation_time).strftime("%H%M%S")
        paths: Dict[str, str] = {"json": "", "markdown": ""}

        # JSON
        json_name = f"{format_date_str(date)}_{ts_label}.json"
        json_path = self.json_dir / json_name
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(diary_data, f, ensure_ascii=False, indent=2)
        paths["json"] = str(json_path)

        # Markdown（仅本地留存，**绝不**经任何接口输出）
        if write_markdown:
            md_path = self.markdown_dir / f"{format_date_str(date)}.md"
            header = markdown_header_template.format(date=format_date_str(date))
            footer = markdown_footer_template.format(
                generated_at=datetime.datetime.fromtimestamp(generation_time).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )
            content = str(diary_data.get("diary_content") or "")
            with md_path.open("w", encoding="utf-8") as f:
                f.write(header + content + footer)
            paths["markdown"] = str(md_path)

        await self._increment_index(str(diary_data.get("status", "")))
        return paths

    # ===== 读取 =====

    async def get_diary(self, date: str) -> Optional[Dict[str, Any]]:
        """获取指定日期最新一条日记（取 JSON）。"""
        diaries = await self.get_diaries_by_date(date)
        if not diaries:
            return None
        return max(diaries, key=lambda d: d.get("generation_time", 0))

    async def get_diaries_by_date(self, date: str) -> List[Dict[str, Any]]:
        """指定日期所有日记（按 generation_time 升序）。"""
        try:
            if not self.json_dir.exists():
                return []
            prefix = f"{format_date_str(date)}_"
            results: List[Dict[str, Any]] = []
            for filename in os.listdir(self.json_dir):
                if filename.startswith(prefix) and filename.endswith(".json"):
                    file_path = self.json_dir / filename
                    try:
                        with file_path.open("r", encoding="utf-8") as f:
                            results.append(json.load(f))
                    except Exception as exc:
                        logger.warning("读日记 %s 失败: %s", filename, exc)
            results.sort(key=lambda d: d.get("generation_time", 0))
            return results
        except Exception as exc:
            logger.error("读日期日记失败: %s", exc, exc_info=True)
            return []

    async def list_diaries(self, limit: int = 10) -> List[Dict[str, Any]]:
        """最近 limit 条（0 = 不限），按 generation_time 降序。"""
        try:
            if not self.json_dir.exists():
                return []
            results: List[Dict[str, Any]] = []
            for filename in os.listdir(self.json_dir):
                if not filename.endswith(".json"):
                    continue
                try:
                    with (self.json_dir / filename).open("r", encoding="utf-8") as f:
                        results.append(json.load(f))
                except Exception as exc:
                    logger.warning("读日记 %s 失败: %s", filename, exc)
            results.sort(key=lambda d: d.get("generation_time", 0), reverse=True)
            return results[:limit] if limit > 0 else results
        except Exception as exc:
            logger.error("列日记失败: %s", exc, exc_info=True)
            return []

    async def get_stats(self) -> Dict[str, Any]:
        try:
            diaries = await self.list_diaries(limit=0)
            if not diaries:
                return {"total_count": 0, "total_words": 0, "avg_words": 0, "latest_date": "无"}
            total_count = len(diaries)
            total_words = sum(d.get("word_count", 0) for d in diaries)
            avg_words = total_words // total_count
            latest_date = max(diaries, key=lambda d: d.get("generation_time", 0)).get("date", "无")
            return {
                "total_count": total_count,
                "total_words": total_words,
                "avg_words": avg_words,
                "latest_date": latest_date,
            }
        except Exception as exc:
            logger.error("get_stats 失败: %s", exc, exc_info=True)
            return {"total_count": 0, "total_words": 0, "avg_words": 0, "latest_date": "无"}

    # ===== 防重状态 =====

    def read_last_diary_date(self) -> Optional[str]:
        """读取最近一次成功生成日期。"""
        try:
            if not self._state_file.exists():
                return None
            value = self._state_file.read_text(encoding="utf-8").strip()
            return value or None
        except Exception as exc:
            logger.warning("读 last_diary_date 失败: %s", exc)
            return None

    def write_last_diary_date(self, date: str) -> None:
        """写入最近一次成功生成日期。"""
        try:
            self._state_file.write_text(format_date_str(date) + "\n", encoding="utf-8")
        except Exception as exc:
            logger.error("写 last_diary_date 失败: %s", exc)

    def read_last_pushed_diary_date(self) -> Optional[str]:
        """读取最近一次成功推送「正常日记」的日期（YYYY-MM-DD）。"""
        return self._read_push_marker(self._diary_push_state_file)

    def write_last_pushed_diary_date(self, date: str) -> None:
        """写入最近一次成功推送「正常日记」的日期。"""
        self._write_push_marker(self._diary_push_state_file, date)

    def read_last_pushed_error_date(self) -> Optional[str]:
        """读取最近一次成功推送「失败消息」的日期（YYYY-MM-DD）。"""
        return self._read_push_marker(self._error_push_state_file)

    def write_last_pushed_error_date(self, date: str) -> None:
        """写入最近一次成功推送「失败消息」的日期。"""
        self._write_push_marker(self._error_push_state_file, date)

    # ===== 重试状态（软失败退避重试） =====

    def read_retry_state(self) -> Optional[Dict[str, Any]]:
        """读取重试状态；文件不存在或结构损坏返回 None。

        返回形如 ``{"date": "YYYY-MM-DD", "attempts_done": int, "next_retry_ts": float}``。
        """
        try:
            if not self._retry_state_file.exists():
                return None
            with self._retry_state_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("date"):
                return data
            logger.warning("retry_state 结构非法，忽略: %s", data)
            return None
        except Exception as exc:
            logger.warning("读 retry_state 失败: %s", exc)
            return None

    def write_retry_state(
        self,
        *,
        date: str,
        attempts_done: int,
        next_retry_ts: float,
    ) -> None:
        """写入重试状态。

        ``next_retry_ts`` 必须是 ``time.time()`` 体系的**绝对 unix 时间戳**
        （调度器按"剩余秒数"折算写入），不要传配置时区下的墙钟时间戳——
        ``local_now()`` 在部分环境返回偏移后的墙钟，直接 ``.timestamp()`` 会错位。
        """
        payload = {
            "date": format_date_str(date),
            "attempts_done": int(attempts_done),
            "next_retry_ts": float(next_retry_ts),
            "updated_at": time.time(),
        }
        try:
            with self._retry_state_file.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("写 retry_state 失败: %s", exc)

    def clear_retry_state(self) -> None:
        """清除重试状态（成功 / 预算耗尽 / 放弃时调用）。"""
        try:
            self._retry_state_file.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("清除 retry_state 失败: %s", exc)

    # ===== 内部 =====

    def _read_push_marker(self, path: Path) -> Optional[str]:
        """读推送标记；新文件缺失时回退旧 ``last_pushed_date.txt``（惰性迁移，不回写）。

        回退语义：旧版本单通道推过哪一天，就视为新版本的两个通道都推过该天，
        避免升级当天把已有日记/失败消息再推一遍。
        """
        value = self._read_text_state(path)
        if value is not None:
            return value
        legacy = self._read_text_state(self._legacy_push_state_file)
        if legacy is not None:
            logger.debug("推送状态惰性迁移: %s 缺失，回退旧 last_pushed_date=%s", path.name, legacy)
        return legacy

    def _write_push_marker(self, path: Path, date: str) -> None:
        try:
            path.write_text(format_date_str(date) + "\n", encoding="utf-8")
        except Exception as exc:
            logger.error("写推送状态 %s 失败: %s", path.name, exc)

    @staticmethod
    def _read_text_state(path: Path) -> Optional[str]:
        """读单值文本状态文件；不存在返回 None。"""
        try:
            if not path.exists():
                return None
            value = path.read_text(encoding="utf-8").strip()
            return value or None
        except Exception as exc:
            logger.warning("读状态文件 %s 失败: %s", path.name, exc)
            return None

    def _read_index(self) -> Dict[str, Any]:
        """读索引文件；不存在或损坏返回默认值。"""
        try:
            if self.index_file.exists():
                with self.index_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {
            "last_update": 0.0,
            "total_diaries": 0,
            "success_count": 0,
            "failed_count": 0,
        }

    async def _increment_index(self, status: str) -> None:
        """增量更新索引：按本次保存结果 +1，不再全量扫描 json 目录（O(1)）。"""
        try:
            index_data = self._read_index()
            if str(status) == "生成成功":
                index_data["success_count"] = int(index_data.get("success_count", 0)) + 1
            else:
                index_data["failed_count"] = int(index_data.get("failed_count", 0)) + 1
            index_data["total_diaries"] = (
                int(index_data.get("success_count", 0)) + int(index_data.get("failed_count", 0))
            )
            index_data["last_update"] = time.time()
            with self.index_file.open("w", encoding="utf-8") as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("更新索引失败: %s", exc)


__all__ = ["DiaryStorage"]
