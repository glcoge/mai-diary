"""消息字段访问（diary 插件统一 seam）。

字段规则对齐主程序 ``src/chat/message_receive/message.py``：
- 私聊判定 = ``"group" if message_info.group_info else "private"``
- 正文取 ``processed_plain_text``

新 SDK 下消息形态是 dict（host 序列化），用 ``msg.get(...)`` 访问。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Tuple


def msg_time(msg: Dict[str, Any]) -> float:
    """取消息时间戳（float 秒）；失败返回 0.0。"""
    raw = msg.get("timestamp", 0) or msg.get("time", 0)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def msg_text(msg: Dict[str, Any]) -> str:
    """取消息正文（processed_plain_text）。"""
    return str(msg.get("processed_plain_text") or "")


def msg_user_id(msg: Dict[str, Any]) -> str:
    """取消息用户 ID（message_info.user_info.user_id）。"""
    info = msg.get("message_info") or {}
    user = info.get("user_info") or {}
    return str(user.get("user_id", "") or "")


def msg_group_id(msg: Dict[str, Any]) -> str:
    """取消息群 ID（message_info.group_info.group_id）。"""
    info = msg.get("message_info") or {}
    group = info.get("group_info") or {}
    return str(group.get("group_id", "") or "")


def msg_user(msg: Dict[str, Any]) -> Tuple[str, str]:
    """取 (用户 ID, 昵称)。昵称优先 user_nickname，回退 user_cardname，再回退"某人"。"""
    info = msg.get("message_info") or {}
    user = info.get("user_info") or {}
    return (
        str(user.get("user_id", "") or ""),
        str(user.get("user_nickname") or user.get("user_cardname") or "某人"),
    )


def is_image(msg: Dict[str, Any]) -> bool:
    """是图片消息吗？"""
    if msg.get("is_picture") or msg.get("is_picid"):
        return True
    text = msg_text(msg).lower()
    if re.search(r"\[picid:[a-f0-9\-]+\]", text):
        return True
    if "[图片" in text or "[image" in text:
        return True
    raw = msg.get("raw_message") or []
    if isinstance(raw, list):
        for seg in raw:
            if isinstance(seg, dict) and str(seg.get("type", "")).lower() in (
                "image",
                "picture",
                "img",
            ):
                return True
    return False


def image_description(msg: Dict[str, Any]) -> str:
    """从 raw_message 找图片描述/alt 文本。"""
    raw = msg.get("raw_message") or []
    if not isinstance(raw, list):
        return ""
    for seg in raw:
        if not isinstance(seg, dict):
            continue
        if str(seg.get("type", "")).lower() not in ("image", "picture", "img"):
            continue
        data = seg.get("data") or {}
        if isinstance(data, dict):
            for key in ("description", "summary", "alt", "file"):
                val = data.get(key)
                if val:
                    return str(val)
    return ""


def is_private(msg: Dict[str, Any]) -> bool:
    """判断消息是否为私聊。

    与 narrative 插件 ``is_private_chat`` 同一套规则，对齐主程序 message.py:61：
    truthy 判断——group_info 非空 dict 才是群聊，空 dict / None / 缺失一律私聊；
    旧字段（is_private/chat_type/scene/detail_type）仅作兜底。
    """
    msg_info = msg.get("message_info")
    if isinstance(msg_info, dict):
        group_info = msg_info.get("group_info")
        if group_info:
            return False
        return True
    if msg.get("is_private") is True:
        return True
    chat_type = (
        msg.get("chat_type") or msg.get("scene") or msg.get("detail_type") or ""
    )
    return str(chat_type) in ("private", "direct")


__all__ = [
    "msg_time",
    "msg_text",
    "msg_user_id",
    "msg_group_id",
    "msg_user",
    "is_image",
    "image_description",
    "is_private",
]
