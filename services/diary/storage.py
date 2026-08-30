"""日记落盘：JSON + Markdown。

布局（base_dir 默认 ``data/diary``）：

- ``data/diary/json/YYYY-MM-DD_HHMMSS.json``  结构化记录（命令 / Tool / API 读取）
- ``data/diary/markdown/YYYY-MM-DD.md``       本地留存，纯展示（不经任何接口输出）
- ``data/diary_index.json``                    索引
- ``data/diary/last_diary_date.txt``          最近一次生成日期（防重复）
- ``data/diary/last_pushed_date.txt``         最近一次推送日期（防重复推送）
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
        self.index_file = self._base / "diary_index.json"
        self._state_file = self._base / "last_diary_date.txt"
        self._push_state_file = self._base / "last_pushed_date.txt"
        self._base.mkdir(parents=True, exist_ok=True)
        self.json_dir.mkdir(parents=True, exist_ok=True)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)
        self.index_file.parent.mkdir(parents=True, exist_ok=True)

    # ===== 写入 =====

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

        await self._update_index()
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

    def read_last_pushed_date(self) -> Optional[str]:
        """读取最近一次成功推送日期（YYYY-MM-DD）。"""
        try:
            if not self._push_state_file.exists():
                return None
            value = self._push_state_file.read_text(encoding="utf-8").strip()
            return value or None
        except Exception as exc:
            logger.warning("读 last_pushed_date 失败: %s", exc)
            return None

    def write_last_pushed_date(self, date: str) -> None:
        """写入最近一次成功推送日期。"""
        try:
            self._push_state_file.write_text(format_date_str(date) + "\n", encoding="utf-8")
        except Exception as exc:
            logger.error("写 last_pushed_date 失败: %s", exc)

    # ===== 内部 =====

    async def _update_index(self) -> None:
        try:
            index_data: Dict[str, Any] = {
                "last_update": time.time(),
                "total_diaries": 0,
                "success_count": 0,
                "failed_count": 0,
            }
            if not self.json_dir.exists():
                with self.index_file.open("w", encoding="utf-8") as f:
                    json.dump(index_data, f, ensure_ascii=False, indent=2)
                return
            success = failed = 0
            for filename in os.listdir(self.json_dir):
                if not filename.endswith(".json"):
                    continue
                try:
                    with (self.json_dir / filename).open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("status") == "生成成功":
                        success += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
            index_data.update({
                "success_count": success,
                "failed_count": failed,
                "total_diaries": success + failed,
            })
            with self.index_file.open("w", encoding="utf-8") as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("更新索引失败: %s", exc)


__all__ = ["DiaryStorage"]
