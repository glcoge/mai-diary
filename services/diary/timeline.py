"""聊天时间线构建 + 情感天气推断。

新 SDK 下消息形态是 dict（host 序列化），用 msg.get(...) 访问。
"""

from __future__ import annotations

import datetime
import random
from typing import Any, Dict, List

from ...utils import get_logger
from .message import image_description, is_image, msg_text, msg_time, msg_user

logger = get_logger(__name__)


class TimelineBuilder:
    """构建按小时分段的聊天时间线。"""

    def __init__(
        self,
        bot_qq_account: str = "",
        *,
        per_message_max_chars: int = 200,
    ) -> None:
        """
        Args:
            bot_qq_account: bot 自己的 QQ，用于把 bot 的消息标记为"我"。
            per_message_max_chars: 单条消息文本最大字符数，超出截断为
                ``<前缀>...``。``0`` 表示不截断（最后会有整体 token 截断兜底）。
        """
        self.bot_qq_account = str(bot_qq_account or "")
        self.per_message_max_chars = max(0, int(per_message_max_chars or 0))
        self._stats: Dict[str, int] = {
            "total_messages": 0,
            "bot_messages": 0,
            "user_messages": 0,
        }

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def build(self, messages: List[Dict[str, Any]]) -> str:
        """聚合消息列表为时间线文本。"""
        if not messages:
            self._stats = {"total_messages": 0, "bot_messages": 0, "user_messages": 0}
            return "今天没有什么特别的对话。"

        parts: List[str] = []
        current_hour = -1
        bot_count = user_count = 0

        for msg in messages:
            ts = msg_time(msg)
            try:
                dt = datetime.datetime.fromtimestamp(ts)
            except (OSError, OverflowError, ValueError):
                continue
            hour = dt.hour
            if hour != current_hour:
                if 6 <= hour < 12:
                    period = f"上午{hour}点"
                elif 12 <= hour < 18:
                    period = f"下午{hour}点"
                else:
                    period = f"晚上{hour}点"
                parts.append(f"\n【{period}】")
                current_hour = hour

            user_id, nickname = msg_user(msg)
            is_bot = bool(self.bot_qq_account) and user_id == self.bot_qq_account

            if is_image(msg):
                desc = image_description(msg)
                tag = f"[图片]{desc}" if desc else "[图片]"
                prefix = "我" if is_bot else nickname
                parts.append(f"{prefix}: {tag}")
            else:
                text = msg_text(msg)
                if (
                    self.per_message_max_chars > 0
                    and text
                    and len(text) > self.per_message_max_chars
                ):
                    text = text[: self.per_message_max_chars] + "..."
                prefix = "我" if is_bot else nickname
                parts.append(f"{prefix}: {text}")

            if is_bot:
                bot_count += 1
            else:
                user_count += 1

        self._stats = {
            "total_messages": len(messages),
            "bot_messages": bot_count,
            "user_messages": user_count,
        }
        return "\n".join(parts)


def weather_by_emotion(messages: List[Dict[str, Any]]) -> str:
    """根据消息文本的关键词频率粗略推断'天气'。"""
    if not messages:
        return random.choice(["晴", "多云", "阴", "多云转晴"])

    content = " ".join(msg_text(m) for m in messages)
    happy = sum(1 for w in ("哈哈", "笑", "开心", "高兴", "棒", "好", "赞", "爱", "喜欢") if w in content)
    sad = sum(1 for w in ("难过", "伤心", "哭", "痛苦", "失望") if w in content)
    angry = sum(1 for w in ("无语", "醉了", "服了", "烦", "气", "怒") if w in content)
    calm = sum(1 for w in ("平静", "安静", "淡定", "还好", "一般") if w in content)

    if happy >= 2:
        return "晴"
    if happy >= 1:
        return "多云转晴"
    if sad >= 1:
        return "雨"
    if angry >= 1:
        return "阴"
    if calm >= 1:
        return "多云"
    return "多云"


__all__ = ["TimelineBuilder", "weather_by_emotion"]
