"""mai-diary 工具模块。"""

from ._envelope import peel_envelope
from ._logging import PLUGIN_ID, get_logger
from .ctx_config import get_global, get_global_float, get_global_list, get_global_str
from .date import (
    date_with_weather,
    diary_window_for_date,
    format_date_str,
    parse_clock,
    parse_date,
    today_str,
    yesterday_str,
)
from .tokens import (
    MAX_DIARY_LENGTH,
    MIN_MESSAGE_COUNT,
    TOKEN_LIMIT_50K,
    estimate_tokens,
    smart_truncate,
    truncate_by_tokens,
)

__all__ = [
    "peel_envelope",
    "PLUGIN_ID",
    "get_logger",
    "get_global",
    "get_global_str",
    "get_global_list",
    "get_global_float",
    "parse_date",
    "format_date_str",
    "today_str",
    "yesterday_str",
    "date_with_weather",
    "parse_clock",
    "diary_window_for_date",
    "estimate_tokens",
    "smart_truncate",
    "truncate_by_tokens",
    "TOKEN_LIMIT_50K",
    "MAX_DIARY_LENGTH",
    "MIN_MESSAGE_COUNT",
]
