"""日期解析、格式化与时间窗计算。"""

from __future__ import annotations

import datetime
import re
from typing import Optional, Tuple


_RELATIVE_MAP = {"今天": 0, "昨天": -1, "前天": -2}


def parse_date(date_str: str) -> Optional[str]:
    """解析日期字符串，返回 YYYY-MM-DD 或 None。

    支持：今天/昨天/前天、YYYY-MM-DD、YYYY/MM/DD、YYYY.MM.MD。
    """
    if not date_str:
        return None
    text = date_str.strip()
    if text in _RELATIVE_MAP:
        delta = _RELATIVE_MAP[text]
        return (datetime.datetime.now() + datetime.timedelta(days=delta)).strftime("%Y-%m-%d")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", text):
        return text
    return None


def format_date_str(date_input) -> str:
    """统一格式化为 YYYY-MM-DD。无法解析则抛 ValueError。"""
    if isinstance(date_input, datetime.datetime):
        return date_input.strftime("%Y-%m-%d")
    if isinstance(date_input, datetime.date):
        return date_input.strftime("%Y-%m-%d")
    if isinstance(date_input, str):
        parsed = parse_date(date_input)
        if parsed:
            return parsed
    raise ValueError(
        f"无法识别的日期格式: {date_input}。支持: YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD / 今天 / 昨天 / 前天"
    )


def today_str() -> str:
    """今天的 YYYY-MM-DD。"""
    return datetime.datetime.now().strftime("%Y-%m-%d")


def yesterday_str() -> str:
    """昨天的 YYYY-MM-DD。"""
    return (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")


def date_with_weather(date: str, weather: str) -> str:
    """组合 '2026年7月27日,星期一,晴。'。"""
    try:
        date_obj = datetime.datetime.strptime(date, "%Y-%m-%d")
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday = weekdays[date_obj.weekday()]
        return f"{date_obj.year}年{date_obj.month}月{date_obj.day}日,{weekday},{weather}。"
    except ValueError:
        return f"{date},{weather}。"


def parse_clock(time_str: str) -> Optional[Tuple[int, int]]:
    """解析 HH:MM，返回 (hour, minute) 或 None。"""
    if not time_str or ":" not in time_str:
        return None
    try:
        hh_s, mm_s = time_str.split(":", 1)
        hh, mm = int(hh_s.strip()), int(mm_s.strip())
    except ValueError:
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh, mm


def diary_window_for_date(
    diary_date: str,
    cutoff_hour: int,
) -> Tuple[float, float, str]:
    """计算某条日记对应的时间窗。

    日记的归属日期是 ``diary_date``，覆盖时间窗为
    ``[diary_date 04:00, diary_date+1 04:00)``（24h 滚动，
    cutoff_hour 通常为 4）。

    Args:
        diary_date: YYYY-MM-DD，日记归属日期。
        cutoff_hour: 切割小时（通常 4），窗口起点为当日 cutoff_hour。

    Returns:
        (start_ts, end_ts, label_date)
        - start_ts: 窗口起点 unix 时间戳。
        - end_ts: 窗口终点 unix 时间戳。
        - label_date: 同 diary_date（便于调用方直接使用）。
    """
    date_obj = datetime.datetime.strptime(diary_date, "%Y-%m-%d")
    start_dt = date_obj.replace(hour=cutoff_hour, minute=0, second=0, microsecond=0)
    end_dt = start_dt + datetime.timedelta(days=1)
    return start_dt.timestamp(), end_dt.timestamp(), diary_date


def local_now(offset_hours: int = 8) -> datetime.datetime:
    """按配置时区返回本地时间（naive、规整到秒）。

    真机踩坑（2026-08-30，源自 narrative 插件）：部分环境（Docker 容器/沙箱）
    墙钟是 +8 时间，但系统时区被注册为 UTC——``datetime.datetime.now(datetime.timezone.utc)``
    返回的竟是墙钟而非真 UTC，再叠加偏移会错 8 小时（作息/日期错位）。

    策略（系统感知）：
    - 系统注册时区 == 目标时区 → 直接信墙钟；
    - 系统注册为 UTC（常见 mislabel）→ 视为"墙钟即本地"，也信墙钟；
    - 其余（注册了其他时区且与目标不同）→ 才用 UTC + 偏移。
    """
    try:
        offset = datetime.datetime.now().astimezone()
        system_hours = (
            float(offset.utcoffset().total_seconds() / 3600) if offset.utcoffset() else 0.0
        )
    except (AttributeError, ValueError, TypeError):
        system_hours = 0.0

    wall = datetime.datetime.now().replace(microsecond=0)
    if abs(system_hours - float(offset_hours)) < 0.01 or abs(system_hours) < 0.01:
        return wall
    utc_naive = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return (utc_naive + datetime.timedelta(hours=int(offset_hours))).replace(microsecond=0)


__all__ = [
    "parse_date",
    "format_date_str",
    "today_str",
    "yesterday_str",
    "date_with_weather",
    "parse_clock",
    "diary_window_for_date",
    "local_now",
]
