"""mai-diary 单元测试。

由于插件目录名包含连字符（``glcoge-mai-diary``），不能直接作为 Python 包名 import。
本测试通过 ``importlib.util.spec_from_file_location`` 把插件挂载到一个**合法
Python 标识符**的合成包名下，模拟 MaiBot 加载器的行为，使 ``from ...utils``
这类相对导入能解析。

运行（项目根）：

    # 1) 用 pytest
    .venv/Scripts/python.exe -m pytest plugins/glcoge-mai-diary/pytests/test_diary.py -q

    # 2) 独立脚本（不依赖 pytest）
    .venv/Scripts/python.exe plugins/glcoge-mai-diary/pytests/test_diary.py
"""

from __future__ import annotations

import asyncio
import datetime
import importlib.util
import os
import sys
import time
import types
from pathlib import Path
from typing import Any, Dict

try:
    import pytest
    _HAS_PYTEST = True
except ImportError:
    _HAS_PYTEST = False

    class _PytestStub:
        """pytest 不可用时的占位。"""

        class _RaisesCtx:
            def __init__(self, exc_type):
                self._exc_type = exc_type

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                if exc is None:
                    raise AssertionError(
                        f"期望抛出 {self._exc_type.__name__}, 实际未抛出"
                    )
                if not issubclass(exc_type, self._exc_type):
                    return False
                return True

        @staticmethod
        def raises(exc_type):
            return _PytestStub._RaisesCtx(exc_type)

    pytest = _PytestStub()  # type: ignore[assignment]


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PLUGIN_ROOT.parent.parent

# 用一个合法的 Python 标识符作为合成包名。
_SYNTH_PKG = "_mai_diary_test_plugin"


def _install_synth_package() -> None:
    """注册合成包并把 plugin_dir 作为其 ``__path__``。"""
    if _SYNTH_PKG in sys.modules:
        return
    mod = types.ModuleType(_SYNTH_PKG)
    mod.__path__ = [str(PLUGIN_ROOT)]  # type: ignore[attr-defined]
    sys.modules[_SYNTH_PKG] = mod


def _register_package(rel_name: str) -> None:
    """把 ``_SYNTH_PKG.<rel_name>`` 注册为一个空包（带 __path__），用于支持相对导入。"""
    full_name = f"{_SYNTH_PKG}.{rel_name}" if rel_name else _SYNTH_PKG
    if full_name in sys.modules:
        return
    # 先注册父包
    if "." in full_name:
        parent = full_name.rsplit(".", 1)[0]
        if parent != _SYNTH_PKG:
            _register_package(parent[len(_SYNTH_PKG) + 1:])
    mod = types.ModuleType(full_name)
    mod.__path__ = [str(PLUGIN_ROOT / rel_name.replace(".", "/"))]  # type: ignore[attr-defined]
    sys.modules[full_name] = mod


def _load_submodule(rel_name: str, file_path: Path):
    """加载插件内的子模块，模块名 = ``_SYNTH_PKG.<rel_name>``。"""
    full_name = f"{_SYNTH_PKG}.{rel_name}" if rel_name else _SYNTH_PKG
    # 先注册各级包
    parts = rel_name.split(".") if rel_name else []
    for i in range(1, len(parts) + 1):
        _register_package(".".join(parts[:i]))
    spec = importlib.util.spec_from_file_location(
        full_name,
        str(file_path),
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块 {full_name} from {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


_install_synth_package()

# 按依赖顺序加载子模块（utils 在 services 之前）。
_UTILS_PKG = _load_submodule(
    "utils", PLUGIN_ROOT / "utils" / "__init__.py"
)
_DATE = _load_submodule("utils.date", PLUGIN_ROOT / "utils" / "date.py")
_TOKENS = _load_submodule("utils.tokens", PLUGIN_ROOT / "utils" / "tokens.py")
_FETCHER = _load_submodule(
    "services.diary.fetcher",
    PLUGIN_ROOT / "services" / "diary" / "fetcher.py",
)
_TIMELINE = _load_submodule(
    "services.diary.timeline",
    PLUGIN_ROOT / "services" / "diary" / "timeline.py",
)
_STORAGE = _load_submodule(
    "services.diary.storage",
    PLUGIN_ROOT / "services" / "diary" / "storage.py",
)
_BRIDGE = _load_submodule(
    "services.diary.narrative_bridge",
    PLUGIN_ROOT / "services" / "diary" / "narrative_bridge.py",
)
_LLM_RUNNER = _load_submodule(
    "services.diary.llm_runner",
    PLUGIN_ROOT / "services" / "diary" / "llm_runner.py",
)
_PIPELINE = _load_submodule(
    "services.diary.pipeline",
    PLUGIN_ROOT / "services" / "diary" / "pipeline.py",
)
_PROMPTS = _load_submodule(
    "services.diary.prompts",
    PLUGIN_ROOT / "services" / "diary" / "prompts.py",
)
_NTFY = _load_submodule(
    "services.diary.ntfy_notifier",
    PLUGIN_ROOT / "services" / "diary" / "ntfy_notifier.py",
)
_SCHEDULER = _load_submodule(
    "services.diary.scheduler",
    PLUGIN_ROOT / "services" / "diary" / "scheduler.py",
)

# narrative 插件的独立存储实现（幂等测试用；无相对依赖，可独立加载）
_NARR_STORE = _load_submodule(
    "narrative_store",
    PROJECT_ROOT / "plugins" / "glcoge-mai-narrative" / "services" / "store.py",
)

parse_date = _DATE.parse_date
format_date_str = _DATE.format_date_str
date_with_weather = _DATE.date_with_weather
parse_clock = _DATE.parse_clock
diary_window_for_date = _DATE.diary_window_for_date

estimate_tokens = _TOKENS.estimate_tokens
smart_truncate = _TOKENS.smart_truncate
truncate_by_tokens = _TOKENS.truncate_by_tokens

MessageFetcher = _FETCHER.MessageFetcher
_parse_target_config = _FETCHER._parse_target_config

TimelineBuilder = _TIMELINE.TimelineBuilder

NtfyNotifier = _NTFY.NtfyNotifier
weather_by_emotion = _TIMELINE.weather_by_emotion

DiaryStorage = _STORAGE.DiaryStorage
NarrativeBridge = _BRIDGE.NarrativeBridge
DiaryPipeline = _PIPELINE.DiaryPipeline
DiaryScheduler = _SCHEDULER.DiaryScheduler
build_narrative_status = _PROMPTS.build_narrative_status
NarrativeStore = _NARR_STORE.NarrativeStore


# ===== 工具方法 =====


def test_parse_clock():
    assert parse_clock("04:00") == (4, 0)
    assert parse_clock("23:59") == (23, 59)
    assert parse_clock("24:00") is None
    assert parse_clock("12:60") is None
    assert parse_clock("abc") is None
    assert parse_clock("") is None
    assert parse_clock(None) is None  # type: ignore[arg-type]


def test_parse_date():
    assert parse_date("今天") == datetime.datetime.now().strftime("%Y-%m-%d")
    assert parse_date("昨天") == (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    assert parse_date("2026-07-27") == "2026-07-27"
    assert parse_date("2026/07/27") == "2026-07-27"
    assert parse_date("2026.07.27") == "2026-07-27"
    assert parse_date("xxx") is None
    assert parse_date("") is None


def test_format_date_str():
    assert format_date_str("2026-07-27") == "2026-07-27"
    with pytest.raises(ValueError):
        format_date_str("xxx")


def test_date_with_weather():
    out = date_with_weather("2026-07-27", "晴")
    assert "2026年7月27日" in out
    assert "晴" in out


def test_diary_window_for_date():
    start, end, label = diary_window_for_date("2026-07-27", cutoff_hour=4)
    assert label == "2026-07-27"
    assert end - start == 24 * 3600
    start_dt = datetime.datetime.fromtimestamp(start)
    assert (start_dt.hour, start_dt.minute) == (4, 0)


# ===== Token / 截断 =====


def test_estimate_tokens_chinese_heavy():
    text = "今天天气真好，我们一起去公园散步" * 10
    n = estimate_tokens(text)
    assert n > 0


def test_truncate_by_tokens_short():
    text = "今天天气真好，我们一起去公园散步"
    assert truncate_by_tokens(text, 50000) == text


def test_truncate_by_tokens_long():
    text = "今天天气真好，我们一起去公园散步。" * 500
    out = truncate_by_tokens(text, 100)
    assert len(out) < len(text)
    assert "已截断" in out


def test_smart_truncate_short():
    text = "今天天气真好。"
    assert smart_truncate(text, 100) == text


def test_smart_truncate_long():
    text = "今天天气真好。" * 200
    out = smart_truncate(text, 100)
    assert len(out) <= 100


# ===== target_chats 解析 =====


def test_parse_target_config():
    private, group = _parse_target_config([
        "group:123456",
        "private:789012",
        "  ",
        "555000",
    ])
    assert group == ["123456", "555000"]
    assert private == ["789012"]


# ===== Timeline =====


def _make_msg(ts: float, user_id: str, nickname: str, text: str) -> Dict[str, Any]:
    return {
        "timestamp": ts,
        "processed_plain_text": text,
        "message_info": {
            "user_info": {"user_id": user_id, "user_nickname": nickname},
        },
        "session_id": "s1",
    }


def test_timeline_build_marks_bot_and_user():
    base = datetime.datetime(2026, 7, 27, 8, 0, 0).timestamp()
    msgs = [
        _make_msg(base + 0, "bot", "Bot", "早安"),
        _make_msg(base + 60, "u1", "Alice", "早上好"),
        _make_msg(base + 3600, "u2", "Bob", "中午见"),
    ]
    builder = TimelineBuilder(bot_qq_account="bot", per_message_max_chars=200)
    out = builder.build(msgs)
    assert "我: 早安" in out
    assert "Alice: 早上好" in out
    assert "Bob: 中午见" in out
    assert builder.stats["bot_messages"] == 1
    assert builder.stats["user_messages"] == 2


def test_timeline_build_truncates_long_message():
    base = datetime.datetime(2026, 7, 27, 8, 0, 0).timestamp()
    msgs = [
        _make_msg(base, "u1", "Alice", "x" * 500),
    ]
    builder = TimelineBuilder(bot_qq_account="bot", per_message_max_chars=50)
    out = builder.build(msgs)
    assert "..." in out
    assert "x" * 100 not in out


def test_timeline_build_empty():
    builder = TimelineBuilder(bot_qq_account="bot")
    out = builder.build([])
    assert "没有" in out
    assert builder.stats["total_messages"] == 0


def test_weather_by_emotion_happy():
    msgs = [
        _make_msg(0, "u1", "A", "今天好开心，笑死我了，哈哈"),
        _make_msg(0, "u2", "B", "我也觉得很棒呀！"),
    ]
    assert weather_by_emotion(msgs) == "晴"


def test_weather_by_emotion_sad():
    msgs = [_make_msg(0, "u1", "A", "唉，今天有点难过")]
    assert weather_by_emotion(msgs) == "雨"


def test_weather_by_emotion_empty():
    assert weather_by_emotion([]) in {"晴", "多云", "阴", "多云转晴"}


# ===== Fetcher 过滤 =====


def test_fetcher_filter_blacklist_group():
    msgs = [
        {
            "timestamp": 1.0,
            "processed_plain_text": "hi",
            "message_info": {
                "user_info": {"user_id": "u1", "user_nickname": "A"},
                "group_info": {"group_id": "111"},
            },
            "session_id": "g1",
        },
        {
            "timestamp": 2.0,
            "processed_plain_text": "hi",
            "message_info": {
                "user_info": {"user_id": "u1", "user_nickname": "A"},
                "group_info": {"group_id": "222"},
            },
            "session_id": "g2",
        },
    ]
    out = MessageFetcher._filter_blacklist(msgs, ["group:111"])
    assert len(out) == 1
    assert out[0]["message_info"]["group_info"]["group_id"] == "222"


def test_fetcher_filter_min_per_chat():
    msgs = [
        {"timestamp": 1.0, "session_id": "s1", "processed_plain_text": "a"},
        {"timestamp": 2.0, "session_id": "s1", "processed_plain_text": "b"},
        {"timestamp": 3.0, "session_id": "s2", "processed_plain_text": "c"},
    ]
    out = MessageFetcher.filter_min_messages_per_chat(msgs, 2)
    assert len(out) == 2
    assert all(m["session_id"] == "s1" for m in out)


# ===== Storage =====


def test_storage_roundtrip(tmp_path: Path):
    storage = DiaryStorage(base_dir=str(tmp_path / "diary"))
    diary = {
        "date": "2026-07-27",
        "diary_content": "今天很开心！",
        "word_count": 6,
        "generation_time": datetime.datetime(2026, 7, 28, 4, 0, 12).timestamp(),
        "weather": "晴",
        "bot_messages": 5,
        "user_messages": 10,
        "window_start": 0.0,
        "window_end": 86400.0,
        "style": "diary",
        "status": "生成成功",
        "error_message": "",
    }
    paths = asyncio.run(storage.save_diary(
        diary,
        write_markdown=True,
        markdown_header_template="# {date} 日记\n\n",
        markdown_footer_template="\n\n---\n",
    ))
    assert os.path.isfile(paths["json"])
    assert os.path.isfile(paths["markdown"])

    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert md.startswith("# 2026-07-27 日记")
    assert "今天很开心" in md

    loaded = asyncio.run(storage.get_diary("2026-07-27"))
    assert loaded is not None
    assert loaded["diary_content"] == "今天很开心！"
    assert loaded["word_count"] == 6


def test_storage_last_diary_date(tmp_path: Path):
    storage = DiaryStorage(base_dir=str(tmp_path / "diary"))
    assert storage.read_last_diary_date() is None
    storage.write_last_diary_date("2026-07-27")
    assert storage.read_last_diary_date() == "2026-07-27"


def test_storage_push_channels_independent(tmp_path: Path):
    """推送状态双通道：正常日记 / 失败消息各自独立计数。"""
    storage = DiaryStorage(base_dir=str(tmp_path / "diary"))
    assert storage.read_last_pushed_diary_date() is None
    assert storage.read_last_pushed_error_date() is None

    storage.write_last_pushed_diary_date("2026-07-27")
    assert storage.read_last_pushed_diary_date() == "2026-07-27"
    assert storage.read_last_pushed_error_date() is None

    storage.write_last_pushed_error_date("2026/07/28")
    assert storage.read_last_pushed_error_date() == "2026-07-28"
    assert storage.read_last_pushed_diary_date() == "2026-07-27"


def test_storage_legacy_push_marker_lazy_fallback(tmp_path: Path):
    """旧版 last_pushed_date.txt 被两通道回退读取（升级当天不重复推送）。"""
    base = tmp_path / "diary"
    storage = DiaryStorage(base_dir=str(base))
    (base / "last_pushed_date.txt").write_text("2026-07-27\n", encoding="utf-8")

    assert storage.read_last_pushed_diary_date() == "2026-07-27"
    assert storage.read_last_pushed_error_date() == "2026-07-27"

    # 新通道写过之后就只认新文件，不再回退
    storage.write_last_pushed_diary_date("2026-07-28")
    assert storage.read_last_pushed_diary_date() == "2026-07-28"
    assert storage.read_last_pushed_error_date() == "2026-07-27"


def test_storage_retry_state_roundtrip(tmp_path: Path):
    """重试状态落盘 / 读取 / 清除。"""
    storage = DiaryStorage(base_dir=str(tmp_path / "diary"))
    assert storage.read_retry_state() is None

    storage.write_retry_state(date="2026-07-27", attempts_done=1, next_retry_ts=123.5)
    state = storage.read_retry_state()
    assert state is not None
    assert state["date"] == "2026-07-27"
    assert state["attempts_done"] == 1
    assert state["next_retry_ts"] == 123.5

    storage.clear_retry_state()
    assert storage.read_retry_state() is None


def test_storage_list_diaries(tmp_path: Path):
    storage = DiaryStorage(base_dir=str(tmp_path / "diary"))
    for d in ["2026-07-25", "2026-07-26", "2026-07-27"]:
        asyncio.run(storage.save_diary(
            {
                "date": d,
                "diary_content": f"content {d}",
                "word_count": 5,
                "generation_time": datetime.datetime.strptime(d, "%Y-%m-%d").timestamp(),
                "weather": "晴",
                "bot_messages": 0,
                "user_messages": 0,
                "style": "diary",
                "status": "生成成功",
                "error_message": "",
            },
            write_markdown=False,
        ))
    diaries = asyncio.run(storage.list_diaries(limit=10))
    assert len(diaries) == 3
    assert diaries[0]["date"] == "2026-07-27"


# ===== ntfy_notifier =====

from types import SimpleNamespace


def _make_ntfy_cfg(**overrides) -> SimpleNamespace:
    """构造一个最小的 NtfySection mock（用 SimpleNamespace 替代 Pydantic）。"""
    cfg = SimpleNamespace(
        enabled=True,
        server="https://ntfy.sh",
        topic="mai-diary-test",
        auth_token="",
        priority="default",
        tags=["diary", "📔"],
        title_template="新日记  {date}",
        failure_title_template="❌ 日记生成失败  {date}",
        body_footer_template="\n\n—— mai-diary • {word_count}字",
        max_body_chars=2000,
        truncate_suffix="\n\n…（已截断，全文见本地文件）",
        click_action="",
        send_on_failure=True,
        timeout_seconds=10,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def test_ntfy_is_configured():
    assert NtfyNotifier(_make_ntfy_cfg()).is_configured() is True
    assert NtfyNotifier(_make_ntfy_cfg(enabled=False)).is_configured() is False
    assert NtfyNotifier(_make_ntfy_cfg(topic="")).is_configured() is False
    assert NtfyNotifier(_make_ntfy_cfg(topic="  ")).is_configured() is False


def test_ntfy_build_body_with_footer():
    n = NtfyNotifier(_make_ntfy_cfg())
    body = n._build_body("今天很开心。", 5)
    assert body.startswith("今天很开心。")
    assert "—— mai-diary • 5字" in body


def test_ntfy_build_body_truncates_long_content():
    long_text = "今天很开心。" * 100  # 600 chars
    n = NtfyNotifier(_make_ntfy_cfg(max_body_chars=100))
    body = n._build_body(long_text, 600)
    assert len(body) < len(long_text)
    assert "已截断" in body


def test_ntfy_build_body_no_footer_when_template_empty():
    n = NtfyNotifier(_make_ntfy_cfg(body_footer_template=""))
    body = n._build_body("hi", 2)
    assert body == "hi"


def test_ntfy_build_body_handles_empty_content():
    n = NtfyNotifier(_make_ntfy_cfg())
    body = n._build_body("", 0)
    assert "—— mai-diary • 0字" in body


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def read(self) -> bytes:
        return b'{"id":"fake"}'


class _FakeConnection:
    """替代 _Utf8HTTPSConnection / _Utf8HTTPConnection。

    - classmethod ``configure`` 一次性设置所有实例的状态
    - 每次构造时把 self 追加到 ``instances`` 列表
    """

    instances: list = []

    @classmethod
    def configure(cls, status: int = 200, raise_exc=None) -> None:
        cls._status = status
        cls._raise = raise_exc
        cls.instances = []

    def __init__(self, host, port=None, timeout=None, **kwargs):
        self.captured: dict = {
            "host": host,
            "port": port,
            "timeout": timeout,
            "method": None,
            "url": None,
            "body": None,
            "headers": None,
        }
        type(self).instances.append(self)

    def request(self, method, url, body=None, headers=None, **kwargs):
        self.captured["method"] = method
        self.captured["url"] = url
        self.captured["body"] = body
        self.captured["headers"] = dict(headers) if headers else {}
        if type(self)._raise is not None:
            raise type(self)._raise

    def getresponse(self):
        if type(self)._raise is not None:
            raise type(self)._raise
        return _FakeResponse(type(self)._status)

    def close(self):
        pass


def _patch_connections():
    """替换 notifier 的 _Utf8HTTP(S)Connection 为 _FakeConnection；返回 restore 函数。"""
    orig_https = _NTFY._Utf8HTTPSConnection
    orig_http = _NTFY._Utf8HTTPConnection
    _NTFY._Utf8HTTPSConnection = _FakeConnection
    _NTFY._Utf8HTTPConnection = _FakeConnection

    def restore():
        _NTFY._Utf8HTTPSConnection = orig_https
        _NTFY._Utf8HTTPConnection = orig_http

    return restore


def test_ntfy_send_diary_posts_correct_request():
    """模拟 ntfy 返回 200，验证 URL / 方法 / 头 / body。"""
    _FakeConnection.configure(status=200)
    restore = _patch_connections()
    try:
        n = NtfyNotifier(_make_ntfy_cfg())
        ok = asyncio.run(n.send_diary(
            date="2026-07-27", content="测试日记", word_count=4, weather="晴",
        ))
    finally:
        restore()

    assert ok is True
    assert len(_FakeConnection.instances) == 1
    inst = _FakeConnection.instances[0]
    assert inst.captured["host"] == "ntfy.sh"
    assert inst.captured["port"] == 443
    assert inst.captured["method"] == "POST"
    assert inst.captured["url"] == "/mai-diary-test"
    headers = inst.captured["headers"]
    assert headers["Title"] == "新日记  2026-07-27"
    assert "diary" in headers["Tags"]
    assert "📔" in headers["Tags"]
    body_text = inst.captured["body"].decode("utf-8")
    assert "测试日记" in body_text
    assert "—— mai-diary • 4字" in body_text


def test_ntfy_send_diary_respects_enabled_false():
    """enabled=false 时不应发出任何请求。"""
    _FakeConnection.configure(status=200)
    restore = _patch_connections()
    try:
        n = NtfyNotifier(_make_ntfy_cfg(enabled=False))
        ok = asyncio.run(n.send_diary(date="2026-07-27", content="x", word_count=1))
    finally:
        restore()

    assert ok is False
    assert _FakeConnection.instances == []


def test_ntfy_send_diary_handles_413_without_retry():
    """收到 413 不重试，返回 False。"""
    _FakeConnection.configure(status=413)
    restore = _patch_connections()
    try:
        n = NtfyNotifier(_make_ntfy_cfg())
        ok = asyncio.run(n.send_diary(date="2026-07-27", content="x", word_count=1))
    finally:
        restore()

    assert ok is False
    assert len(_FakeConnection.instances) == 1  # 没有重试


def test_ntfy_send_diary_handles_network_exception():
    """网络异常（如 DNS 失败）不抛、不影响主流程。"""
    _FakeConnection.configure(status=200, raise_exc=OSError("dns resolution failed"))
    restore = _patch_connections()
    try:
        n = NtfyNotifier(_make_ntfy_cfg())
        ok = asyncio.run(n.send_diary(date="2026-07-27", content="x", word_count=1))
    finally:
        restore()

    assert ok is False


def test_ntfy_send_failure_uses_failure_template():
    """失败通知走 failure_title_template。"""
    _FakeConnection.configure(status=200)
    restore = _patch_connections()
    try:
        n = NtfyNotifier(_make_ntfy_cfg())
        ok = asyncio.run(n.send_failure(date="2026-07-27", error="消息数不足"))
    finally:
        restore()

    assert ok is True
    headers = _FakeConnection.instances[0].captured["headers"]
    assert headers["Title"] == "❌ 日记生成失败  2026-07-27"


def test_ntfy_send_failure_includes_manual_retry_hint():
    """失败通知正文带手动重试提示（每日最多一条错误消息的兜底入口）。"""
    _FakeConnection.configure(status=200)
    restore = _patch_connections()
    try:
        n = NtfyNotifier(_make_ntfy_cfg())
        ok = asyncio.run(n.send_failure(date="2026-07-27", error="模型返回空"))
    finally:
        restore()

    assert ok is True
    body = _FakeConnection.instances[0].captured["body"]
    assert b"/diary gen 2026-07-27" in body


def test_ntfy_send_failure_kill_switch():
    """send_on_failure=false 时不发任何请求。"""
    _FakeConnection.configure(status=200)
    restore = _patch_connections()
    try:
        n = NtfyNotifier(_make_ntfy_cfg(send_on_failure=False))
        ok = asyncio.run(n.send_failure(date="2026-07-27", error="x"))
    finally:
        restore()

    assert ok is False
    assert _FakeConnection.instances == []


def test_ntfy_auth_token_in_header():
    """自建 ntfy 带 auth_token 时正确设置 Authorization 头。"""
    _FakeConnection.configure(status=200)
    restore = _patch_connections()
    try:
        n = NtfyNotifier(_make_ntfy_cfg(auth_token="tk_xxx"))
        asyncio.run(n.send_diary(date="2026-07-27", content="x", word_count=1))
    finally:
        restore()

    headers = _FakeConnection.instances[0].captured["headers"]
    assert headers.get("Authorization") == "Bearer tk_xxx"


def test_ntfy_url_encodes_topic():
    """topic 含特殊字符时应被 URL 编码。"""
    _FakeConnection.configure(status=200)
    restore = _patch_connections()
    try:
        n = NtfyNotifier(_make_ntfy_cfg(topic="my topic/with spaces"))
        asyncio.run(n.send_diary(date="2026-07-27", content="x", word_count=1))
    finally:
        restore()

    captured_url = _FakeConnection.instances[0].captured["url"]
    assert " " not in captured_url
    assert "%20" in captured_url


def test_ntfy_putheader_handles_utf8():
    """_Utf8HTTPSConnection.putheader 不应被非 ASCII 卡住。

    Python 3.14 行为：putheader 只写 ``Name: Value``（不带 \\r\\n），
    由 _send_output 统一 join \\r\\n。这里要验证 UTF-8 中文/emoji 能进 buffer。
    """
    conn = _NTFY._Utf8HTTPSConnection("ntfy.sh", 443, timeout=5)
    output: list = []
    conn._output = output.append  # type: ignore[assignment]
    conn.putheader("Title", "新日记  2026-07-30")
    conn.putheader("Tags", "diary,📔")
    conn.putheader("Priority", "default")
    assert len(output) == 3
    # 不带 \r\n（由 _send_output 统一 join）
    assert b"Title: \xe6\x96\xb0\xe6\x97\xa5\xe8\xae\xb0  2026-07-30" in output
    assert b"Tags: diary,\xf0\x9f\x93\x94" in output
    assert b"Priority: default" in output
    # 确认没有 \r\n（避免双 \r\n）
    for line in output:
        assert b"\r\n" not in line


# ===== 剧本人设联动（握手适配 2026-08-30） =====

import logging as _stdlib_logging


class _FakeApi:
    """模拟 ctx.api：list 探测 + call 跨插件调用。"""

    def __init__(self, *, api_list=None, context_payload=None, append_payload=None):
        self._api_list = api_list if api_list is not None else [{"name": "narrative_diary_context"}]
        self._context_payload = context_payload
        self._append_payload = append_payload
        self.append_calls: list = []

    async def list(self, plugin_id: str = "") -> list:
        if plugin_id == "glcoge.mai-narrative":
            return self._api_list
        return []

    async def call(self, api_name: str, **kwargs) -> Any:
        if api_name == "glcoge.mai-narrative.narrative_diary_context":
            return dict(self._context_payload or {})
        if api_name == "glcoge.mai-narrative.narrative_chronicle_append":
            self.append_calls.append(kwargs)
            return dict(self._append_payload or {})
        return None


class _FakeConfig:
    """最小 PluginContext.config（config.get 走 dict 查询）。"""

    def __init__(self, values: Dict[str, Any]):
        self._values = values

    async def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)


class _FakeCtx:
    """最小插件上下文：config + api（pipeline 构造所需的字段）。"""

    def __init__(self, *, global_config: Optional[Dict[str, Any]] = None, api: Optional[_FakeApi] = None):
        self.config = _FakeConfig(global_config or {})
        self.api = api if api is not None else _FakeApi()
        self.logger = _stdlib_logging.getLogger("mai-diary-test")

    async def config_get_for_test(self, key: str, default: Any = None) -> Any:
        return await self.config.get(key, default)


def _make_narrative_ctx_payload(
    *,
    narrative_enabled: bool = True,
    mode_user_ids=None,
    mode_stream_ids=None,
    persona: str = "银发狐妖，生活在赛博朋克沿海城市",
    expression: str = "说话简短，轻微社恐",
) -> Dict[str, Any]:
    return {
        "ok": True,
        "available": True,
        "narrative_enabled": narrative_enabled,
        "mode_user_ids": mode_user_ids or ["10001"],
        "mode_stream_ids": mode_stream_ids or [],
        "self_state": {
            "identity_persona": persona,
            "expression_hint": expression,
            "mood_label": "平静",
            "mood_energy": 0.55,
            "mood_shift_ts": "",
            "routine_phase": "上午",
            "hot_thread": "",
            "recent_chronicle": [],
        },
        "today_mood_track": [],
    }


def _make_plugin_config(*, narrative_enabled: bool = True) -> Any:
    """构造 pipeline 所需的 config 结构（SimpleNamespace 嵌套）。"""
    return SimpleNamespace(
        summary=SimpleNamespace(
            use_bot_personality=True,
            style="diary",
            custom_prompt="",
            self_description="",
            min_word_count=100,
            max_word_count=400,
        ),
        narrative=SimpleNamespace(enabled=narrative_enabled),
        output=SimpleNamespace(base_dir="data/diary"),
        schedule=SimpleNamespace(generate_time="04:00", persist_state=False),
        message=SimpleNamespace(
            target_chats="",
            filter_mode="all",
            min_message_count=5,
            min_messages_per_chat=0,
            per_message_max_chars=200,
        ),
        llm=SimpleNamespace(
            text_model="replyer",
            timeout_seconds=30,
            truncate_tokens=50000,
            temperature=0.7,
            show_prompt=False,
        ),
    )


def _make_private_msg(ts: float, user_id: str, nickname: str, text: str, session_id: str) -> Dict[str, Any]:
    """私聊消息（无 group_info 即私聊）。"""
    return {
        "timestamp": ts,
        "processed_plain_text": text,
        "message_info": {
            "user_info": {"user_id": user_id, "user_nickname": nickname},
        },
        "session_id": session_id,
    }


def _make_group_msg(ts: float, user_id: str, nickname: str, text: str, session_id: str, group_id: str = "g100") -> Dict[str, Any]:
    """群聊消息（带 group_info）。"""
    return {
        "timestamp": ts,
        "processed_plain_text": text,
        "message_info": {
            "user_info": {"user_id": user_id, "user_nickname": nickname},
            "group_info": {"group_id": group_id},
        },
        "session_id": session_id,
    }


def test_narrative_bridge_has_mode_session():
    """会话分诊静态判定：私聊白名单命中 / 群聊同号不命中 / 显式 stream 白名单。"""
    data = _make_narrative_ctx_payload(mode_user_ids=["10001"], mode_stream_ids=["s_explicit"])

    # 私聊命中
    msgs = [_make_private_msg(0, "10001", "Alice", "你好", "s1")]
    assert NarrativeBridge._has_mode_session(msgs, data) is True
    # 群聊同号 → 不命中
    msgs = [_make_group_msg(0, "10001", "Alice", "你好", "g1")]
    assert NarrativeBridge._has_mode_session(msgs, data) is False
    # 显式 stream 白名单命中
    msgs = [_make_private_msg(0, "99999", "Bob", "hi", "s_explicit")]
    assert NarrativeBridge._has_mode_session(msgs, data) is True
    # 空数据 → False
    assert NarrativeBridge._has_mode_session(msgs, {}) is False
    assert NarrativeBridge._has_mode_session([], data) is False


async def _resolve_persona_with(
    *,
    messages: List[Dict[str, Any]],
    global_config: Optional[Dict[str, Any]] = None,
    context_payload: Optional[Dict[str, Any]] = None,
    narrative_enabled: bool = True,
    tmp_path: Path,
) -> Dict[str, Any]:
    """构造 pipeline 并执行 _resolve_personality（不触达 LLM / 消息抓取）。"""
    api = _FakeApi(context_payload=context_payload)
    ctx = _FakeCtx(global_config=global_config, api=api)
    cfg = _make_plugin_config(narrative_enabled=narrative_enabled)
    cfg.output.base_dir = str(tmp_path / "diary")
    plugin = SimpleNamespace(ctx=ctx, config=cfg)
    pipeline = DiaryPipeline(plugin)
    personality, expression, bot_qq, narrative_ctx = await pipeline._resolve_personality(messages)
    return {
        "personality": personality,
        "expression": expression,
        "bot_qq": bot_qq,
        "narrative_ctx": narrative_ctx,
    }


def test_pipeline_persona_replaced_in_mode_session(tmp_path: Path):
    """剧本模式会话 → 作者人格改从自我层读取（替代全局 personality）。"""
    messages = [
        _make_private_msg(0, "10001", "Alice", "今天聊得开心", "s1"),
        _make_private_msg(60, "20002", "Bot", "我也是", "s1"),
    ]
    out = asyncio.run(_resolve_persona_with(
        messages=messages,
        # 全局人格是"默认人格"，剧本路径不应使用它
        global_config={"personality.personality": "默认人格", "bot.qq_account": "20002"},
        context_payload=_make_narrative_ctx_payload(),
        tmp_path=tmp_path,
    ))
    assert out["narrative_ctx"] is not None
    assert out["personality"] == "银发狐妖，生活在赛博朋克沿海城市"
    assert "默认人格" not in out["personality"]
    assert out["expression"] == "说话简短，轻微社恐"
    assert out["bot_qq"] == "20002"


def test_pipeline_persona_kept_global_without_mode(tmp_path: Path):
    """无剧本模式会话 → 沿用全局 personality（旧逻辑不破坏）。"""
    messages = [
        _make_group_msg(0, "30001", "Carol", "群里聊", "g1"),
        _make_group_msg(60, "20002", "Bot", "哈哈", "g1"),
    ]
    out = asyncio.run(_resolve_persona_with(
        messages=messages,
        global_config={"personality.personality": "默认人格", "bot.qq_account": "20002"},
        context_payload=_make_narrative_ctx_payload(),
        tmp_path=tmp_path,
    ))
    assert out["narrative_ctx"] is None
    assert out["personality"] == "默认人格"


def test_pipeline_persona_global_when_narrative_disabled(tmp_path: Path):
    """联动开关关闭 → 完全不握手，走全局人格。"""
    messages = [_make_private_msg(0, "10001", "Alice", "你好", "s1")]
    out = asyncio.run(_resolve_persona_with(
        messages=messages,
        global_config={"personality.personality": "默认人格", "bot.qq_account": "20002"},
        context_payload=_make_narrative_ctx_payload(),
        narrative_enabled=False,
        tmp_path=tmp_path,
    ))
    assert out["narrative_ctx"] is None
    assert out["personality"] == "默认人格"


def test_pipeline_narrative_unavailable_degrades(tmp_path: Path):
    """narrative 插件不可用（api.list 空）→ 降级全局人格，不抛异常。"""
    messages = [_make_private_msg(0, "10001", "Alice", "你好", "s1")]
    out = asyncio.run(_resolve_persona_with(
        messages=messages,
        global_config={"personality.personality": "默认人格", "bot.qq_account": "20002"},
        context_payload=None,
        tmp_path=tmp_path,
    ))
    # _FakeApi 默认 api_list 非空，但 context_payload=None → call 返回 {} → 降级
    assert out["narrative_ctx"] is None
    assert out["personality"] == "默认人格"


def test_chronicle_append_idempotent(tmp_path: Path):
    """编年史写入幂等：同一天重跑不重复写（append_chronicle_once）。"""
    store = NarrativeStore(data_dir=tmp_path / "narrative")

    first = store.append_chronicle_once("self", "diary", "今天很开心。", "2026-07-27")
    assert first is True
    assert store.count_chronicle("self") == 1

    # 同一天重跑 → 不重复写
    duplicate = store.append_chronicle_once("self", "diary", "今天很开心。", "2026-07-27")
    assert duplicate is False
    assert store.count_chronicle("self") == 1

    # 不同日期 → 正常写入
    other = store.append_chronicle_once("self", "diary", "第二天。", "2026-07-28")
    assert other is True
    assert store.count_chronicle("self") == 2

    # 空文本从不写入
    blank = store.append_chronicle_once("self", "diary", "   ", "2026-07-29")
    assert blank is False


def test_chronicle_bridge_append_idempotent_via_api(tmp_path: Path):
    """diary 侧 bridge：同一日期二次 append 由 narrative API 判定重复。"""
    api = _FakeApi(append_payload={"ok": True, "written": True, "date": "2026-07-27"})
    ctx = _FakeCtx(api=api)
    cfg = _make_plugin_config()
    plugin = SimpleNamespace(ctx=ctx, config=cfg)
    bridge = NarrativeBridge(plugin)

    first = asyncio.run(bridge.append_chronicle("2026-07-27", "今天很开心。"))
    assert first["written"] is True
    assert first["ok"] is True

    # 第二次：narrative 侧返回 duplicate（written=False），bridge 原样透传
    api._append_payload = {"ok": True, "written": False, "date": "2026-07-27", "reason": "duplicate"}
    second = asyncio.run(bridge.append_chronicle("2026-07-27", "今天很开心。"))
    assert second["written"] is False
    assert second["ok"] is True
    assert second["reason"] == "duplicate"
    assert len(api.append_calls) == 2


def test_narrative_status_builds_from_self_state():
    """prompt 附加段构建：自我层状态 → 文案（情绪轨迹预留透传）。"""
    payload = _make_narrative_ctx_payload()
    payload["today_mood_track"] = ["上午：平静 0.55", "午后：轻快 0.72"]
    ctx = {"data": payload}
    status = build_narrative_status(ctx)
    assert "心情：平静" in status
    assert "精力 6/10" in status
    assert "作息：上午" in status
    assert "今日情绪轨迹" in status


# ===== 调度器：推送双通道 / 失败退避重试 =====
#
# 背景（2026-09-11 改造）：
#   - 推送拆成双通道：同一日记日期最多推 1 条正常日记 + 1 条失败消息；
#   - 软失败（LLM 空返回/超时/异常）按指数退避重试，最多 3 次，成功即停；
#     硬失败（消息数量不足）不重试；手动触发失败不重试；
#   - 重试状态落盘 retry_state.json，重启后预算未尽则续跑；
#   - 重试挂起时推送顺延，重试/手动生成成功且已过 push_time 则跟进补推一次。
#
# 时间相关判定依赖 scheduler._local_now()，测试统一用"冻结时钟"固定在
# 12:00（晚于 push_time=08:00），避免结果随运行时刻漂移。

_FROZEN_NOW = datetime.datetime(2026, 9, 11, 12, 0, 0)
_FROZEN_YESTERDAY = "2026-09-10"


class _FrozenClock:
    """把 scheduler 模块内的 ``local_now`` 冻结到指定时刻。"""

    def __init__(self, moment: datetime.datetime) -> None:
        self._moment = moment
        self._original = None

    def __enter__(self) -> "_FrozenClock":
        self._original = _SCHEDULER.local_now
        _SCHEDULER.local_now = lambda offset_hours=8: self._moment
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        _SCHEDULER.local_now = self._original
        return False


def _make_sched_cfg(
    base_dir: Path,
    *,
    persist_state: bool,
    retry_enabled: bool = True,
    retry_max_attempts: int = 3,
    retry_base_minutes: int = 10,
    retry_max_delay_minutes: int = 120,
) -> SimpleNamespace:
    """构造 scheduler 所需的最小 config（SimpleNamespace 替代 Pydantic）。"""
    return SimpleNamespace(
        output=SimpleNamespace(base_dir=str(base_dir)),
        ntfy=_make_ntfy_cfg(),
        schedule=SimpleNamespace(
            generate_time="04:00",
            push_time="08:00",
            persist_state=persist_state,
            timezone_offset_hours=8,
            check_interval_seconds=60,
        ),
        retry=SimpleNamespace(
            enabled=retry_enabled,
            max_attempts=retry_max_attempts,
            base_delay_minutes=retry_base_minutes,
            max_delay_minutes=retry_max_delay_minutes,
        ),
    )


class _RecordingNotifier:
    """记录推送调用的假 notifier（不发出真实网络请求）。"""

    def __init__(self) -> None:
        self.sent: list = []

    def is_configured(self) -> bool:
        return True

    async def send_diary(self, **kw) -> bool:
        self.sent.append(("diary", str(kw.get("date"))))
        return True

    async def send_failure(self, **kw) -> bool:
        self.sent.append(("failure", str(kw.get("date"))))
        return True


class _RecordingPipeline:
    """记录生成调用的假 pipeline。

    ``outcomes`` 是返回值队列：每次调用弹出队首；队列空时回退为成功。
    测试通过 ``_RecordingPipelineCtx`` 编排失败/成功序列。
    """

    calls: list = []
    outcomes: list = []
    success_writer = None

    def __init__(self, plugin) -> None:
        pass

    async def generate_for_date(self, date: str):
        _RecordingPipeline.calls.append(date)
        if _RecordingPipeline.outcomes:
            outcome = _RecordingPipeline.outcomes.pop(0)
        else:
            outcome = (True, "ok", False)
        # 模拟真机：生成成功会落盘日记记录（跟进补推据此判定）
        if outcome[0] and _RecordingPipeline.success_writer is not None:
            await _RecordingPipeline.success_writer(date)
        return outcome


class _RecordingPipelineCtx:
    """临时代替 scheduler 模块内的 DiaryPipeline 类。"""

    def __init__(self, outcomes, success_writer=None) -> None:
        self._outcomes = list(outcomes)
        self._success_writer = success_writer
        self._original = None

    def __enter__(self) -> type:
        _RecordingPipeline.calls = []
        _RecordingPipeline.outcomes = list(self._outcomes)
        _RecordingPipeline.success_writer = self._success_writer
        self._original = _SCHEDULER.DiaryPipeline
        _SCHEDULER.DiaryPipeline = _RecordingPipeline
        return _RecordingPipeline

    def __exit__(self, exc_type, exc, tb) -> bool:
        _SCHEDULER.DiaryPipeline = self._original
        _RecordingPipeline.outcomes = []
        _RecordingPipeline.success_writer = None
        return False


def _make_scheduler(tmp_path: Path, *, persist_state: bool, **cfg_kwargs):
    """构造 scheduler，并把 notifier 替换为记录型假件。"""
    plugin = SimpleNamespace(
        config=_make_sched_cfg(tmp_path, persist_state=persist_state, **cfg_kwargs)
    )
    sched = DiaryScheduler(plugin)
    sched._notifier = _RecordingNotifier()
    return sched


def _run_recover_with_recording(sched):
    """用记录型假 pipeline 类替换后跑一次启动补跑（_maybe_recover），返回该假类。"""
    with _RecordingPipelineCtx([(True, "ok", False)]) as fake:
        asyncio.run(sched._maybe_recover((4, 0), (8, 0)))
    return fake


def _diary_payload(date: str, *, status: str, generation_time: float) -> dict:
    """构造一条日记记录（成功/报错两种形态）。"""
    success = status == "生成成功"
    return {
        "date": date,
        "status": status,
        "word_count": 100 if success else 0,
        "weather": "晴" if success else "阴",
        "diary_content": "昨天的日记" if success else "",
        "error_message": "" if success else "原因:消息数不足",
        "generation_time": generation_time,
    }


async def _seed_diary_async(
    storage: DiaryStorage,
    date: str,
    *,
    status: str,
    generation_time: float = 1.0,
) -> None:
    """异步落盘一条日记（供事件循环内调用，如假 pipeline 的成功回调）。"""
    await storage.save_diary(
        _diary_payload(date, status=status, generation_time=generation_time)
    )


def _seed_diary(
    storage: DiaryStorage,
    date: str,
    *,
    status: str,
    generation_time: float = 1.0,
) -> None:
    """向临时 storage 写入指定日期/状态的日记。

    同一日期需要多条记录时用递增的 ``generation_time``（决定文件名与"最新"判定）。
    """
    asyncio.run(
        _seed_diary_async(storage, date, status=status, generation_time=generation_time)
    )


def test_restart_no_regen_no_repush_persist_off(tmp_path: Path):
    """回归（用户真机场景）：persist_state=false + 昨天已生成已推送 → 重启零动作。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    sched._storage.write_last_diary_date(_FROZEN_YESTERDAY)
    sched._storage.write_last_pushed_diary_date(_FROZEN_YESTERDAY)
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="生成成功")

    with _FrozenClock(_FROZEN_NOW):
        fake = _run_recover_with_recording(sched)

    assert fake.calls == [], "已有日记数据，不应重新生成"
    assert sched._notifier.sent == [], "已推送的日记不应被重新推送"


def test_restart_no_regen_no_repush_persist_on(tmp_path: Path):
    """persist_state=true 时行为一致：解耦后开关不再影响防重复正确性。"""
    sched = _make_scheduler(tmp_path, persist_state=True)
    sched._storage.write_last_diary_date(_FROZEN_YESTERDAY)
    sched._storage.write_last_pushed_diary_date(_FROZEN_YESTERDAY)
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="生成成功")

    with _FrozenClock(_FROZEN_NOW):
        fake = _run_recover_with_recording(sched)

    assert fake.calls == [], "已有日记数据，不应重新生成"
    assert sched._notifier.sent == [], "已推送的日记不应被重新推送"


def test_restart_no_repush_for_failed_diary(tmp_path: Path):
    """报错日记 + 无重试预算：重启不重生成、不重复推失败消息。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    sched._storage.write_last_pushed_error_date(_FROZEN_YESTERDAY)
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="报错:生成失败")

    with _FrozenClock(_FROZEN_NOW):
        fake = _run_recover_with_recording(sched)

    assert fake.calls == [], "报错日记也属于已有数据，不应重新生成"
    assert sched._notifier.sent == [], "失败消息已推送过，不应重复推送"


def test_restart_recovers_unpushed_diary_once(tmp_path: Path):
    """正常补推送不受影响：昨天日记存在但未推送 → 恰好推送一次并落状态。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="生成成功")

    with _FrozenClock(_FROZEN_NOW):
        fake = _run_recover_with_recording(sched)

        assert fake.calls == [], "已有日记数据，不应重新生成"
        assert sched._notifier.sent == [("diary", _FROZEN_YESTERDAY)]
        # persist_state=false 也必须写入推送状态（幂等的关键）
        assert sched._storage.read_last_pushed_diary_date() == _FROZEN_YESTERDAY

        # 再次重启（第二次补跑）：不再推送
        fake2 = _run_recover_with_recording(sched)
    assert fake2.calls == []
    assert sched._notifier.sent == [("diary", _FROZEN_YESTERDAY)]


def test_recover_still_generates_when_diary_missing(tmp_path: Path):
    """数据存在性判定不误伤补生成：昨天无日记数据 → 补生成照常触发。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    # 即便 last_diary_date 标记声称已生成，数据缺失时仍以数据为准
    sched._storage.write_last_diary_date(_FROZEN_YESTERDAY)

    with _FrozenClock(_FROZEN_NOW):
        fake = _run_recover_with_recording(sched)

    assert fake.calls == [_FROZEN_YESTERDAY]


def test_has_unpushed_yesterday_independent_of_persist_state(tmp_path: Path):
    """推送候选判定：双通道去重不依赖 persist_state。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    sched._storage.write_last_pushed_diary_date(_FROZEN_YESTERDAY)
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="生成成功")

    with _FrozenClock(_FROZEN_NOW):
        assert asyncio.run(sched._has_unpushed_yesterday()) is False

        # 未推送时判定为 True（正常补推送路径保留）
        sched._storage.write_last_pushed_diary_date("2000-01-01")
        assert asyncio.run(sched._has_unpushed_yesterday()) is True


# ===== 失败退避重试 =====


def test_soft_failure_schedules_retry(tmp_path: Path):
    """软失败（LLM 空返回）→ 登记首次退避重试并落盘。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    with _FrozenClock(_FROZEN_NOW):
        with _RecordingPipelineCtx([(False, "模型生成日记失败（返回空）", True)]):
            ok, _ = asyncio.run(
                sched._generate_for_date_safe(_FROZEN_YESTERDAY, source="schedule")
            )

        assert ok is False
        assert sched._retry is not None
        assert sched._retry["date"] == _FROZEN_YESTERDAY
        assert sched._retry["attempts_done"] == 0
        # base=10 分钟 → 下次重试在 12:10
        assert sched._retry["next_at"] == _FROZEN_NOW + datetime.timedelta(minutes=10)

    persisted = sched._storage.read_retry_state()
    assert persisted is not None
    assert persisted["date"] == _FROZEN_YESTERDAY
    assert persisted["attempts_done"] == 0
    # 落盘时间戳按 time.time() 体系（剩余约 600 秒）
    remaining = persisted["next_retry_ts"] - time.time()
    assert 590 < remaining <= 600


def test_hard_failure_not_retried(tmp_path: Path):
    """消息数不足是硬失败：不入队、不写 retry_state。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    with _FrozenClock(_FROZEN_NOW):
        with _RecordingPipelineCtx([(False, "消息数量不足(3/5)", False)]):
            ok, msg = asyncio.run(
                sched._generate_for_date_safe(_FROZEN_YESTERDAY, source="schedule")
            )

    assert ok is False
    assert "消息数量不足" in msg
    assert sched._retry is None
    assert sched._storage.read_retry_state() is None


def test_manual_failure_not_retried(tmp_path: Path):
    """手动 /diary gen 的失败不进入自动重试队列（用户在场，可自行再跑）。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    with _FrozenClock(_FROZEN_NOW):
        with _RecordingPipelineCtx([(False, "生成日记时出错: boom", True)]):
            asyncio.run(
                sched._generate_for_date_safe(_FROZEN_YESTERDAY, source="manual")
            )

    assert sched._retry is None
    assert sched._storage.read_retry_state() is None


def test_retry_disabled_no_schedule(tmp_path: Path):
    """retry.enabled=false → 与旧版本一致，失败即放弃。"""
    sched = _make_scheduler(tmp_path, persist_state=False, retry_enabled=False)
    with _FrozenClock(_FROZEN_NOW):
        with _RecordingPipelineCtx([(False, "模型生成日记失败（返回空）", True)]):
            asyncio.run(
                sched._generate_for_date_safe(_FROZEN_YESTERDAY, source="schedule")
            )

    assert sched._retry is None
    assert sched._storage.read_retry_state() is None


def test_retry_backoff_sequence_and_cap(tmp_path: Path):
    """退避序列 base×2^n 与 max_delay 封顶。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    assert sched._retry_delay_seconds(0) == 600       # 10 分钟
    assert sched._retry_delay_seconds(1) == 1200      # 20 分钟
    assert sched._retry_delay_seconds(2) == 2400      # 40 分钟
    assert sched._retry_delay_seconds(5) == 7200      # 封顶 120 分钟


def test_execute_retry_success_clears_state(tmp_path: Path):
    """重试成功 → 清除内存与落盘状态。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    with _FrozenClock(_FROZEN_NOW):
        sched._schedule_retry(_FROZEN_YESTERDAY, 0, _FROZEN_NOW)
        with _RecordingPipelineCtx([(True, "ok", False)]) as fake:
            asyncio.run(sched._execute_retry())

    assert fake.calls == [_FROZEN_YESTERDAY]
    assert sched._retry is None
    assert sched._storage.read_retry_state() is None


def test_execute_retry_advances_backoff(tmp_path: Path):
    """第 1/2 次重试失败 → 次数递增、间隔按 20/40 分钟推进。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    failures = [(False, "模型生成日记失败（返回空）", True)] * 2
    with _FrozenClock(_FROZEN_NOW):
        sched._schedule_retry(_FROZEN_YESTERDAY, 0, _FROZEN_NOW)
        with _RecordingPipelineCtx(failures):
            asyncio.run(sched._execute_retry())
            assert sched._retry["attempts_done"] == 1
            assert sched._retry["next_at"] == _FROZEN_NOW + datetime.timedelta(minutes=20)

            asyncio.run(sched._execute_retry())
            assert sched._retry["attempts_done"] == 2
            assert sched._retry["next_at"] == _FROZEN_NOW + datetime.timedelta(minutes=40)


def test_execute_retry_budget_exhausted_clears_state(tmp_path: Path):
    """3 次重试全失败 → 预算耗尽、状态清除（最终报错记录交由推送侧提醒）。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    failures = [(False, "模型生成日记失败（返回空）", True)] * 3
    with _FrozenClock(_FROZEN_NOW):
        sched._schedule_retry(_FROZEN_YESTERDAY, 0, _FROZEN_NOW)
        with _RecordingPipelineCtx(failures) as fake:
            asyncio.run(sched._execute_retry())
            asyncio.run(sched._execute_retry())
            asyncio.run(sched._execute_retry())

    assert len(fake.calls) == 3, "首次 + 3 次重试共 4 次尝试中的 3 次重试"
    assert sched._retry is None
    assert sched._storage.read_retry_state() is None


def test_execute_retry_skips_when_success_record_exists(tmp_path: Path):
    """该日期已被手动 gen 修好 → 不消耗重试预算。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="生成成功")
    with _FrozenClock(_FROZEN_NOW):
        sched._schedule_retry(_FROZEN_YESTERDAY, 1, _FROZEN_NOW)
        with _RecordingPipelineCtx([(True, "ok", False)]) as fake:
            asyncio.run(sched._execute_retry())

    assert fake.calls == []
    assert sched._retry is None


def test_retry_state_survives_reload(tmp_path: Path):
    """落盘状态被新实例按"剩余秒数"恢复（不依赖墙钟时区换算）。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    with _FrozenClock(_FROZEN_NOW):
        sched._schedule_retry(
            _FROZEN_YESTERDAY, 2, _FROZEN_NOW + datetime.timedelta(minutes=40)
        )

    revived = _make_scheduler(tmp_path, persist_state=False)
    with _FrozenClock(_FROZEN_NOW):
        revived._load_retry_state()
        assert revived._retry is not None
        assert revived._retry["date"] == _FROZEN_YESTERDAY
        assert revived._retry["attempts_done"] == 2
        remaining = (revived._retry["next_at"] - _FROZEN_NOW).total_seconds()
    assert 2390 < remaining <= 2400


def test_recover_resumes_pending_retry(tmp_path: Path):
    """重启续跑：报错记录 + 预算未尽 → 恢复重试（不在补跑阶段直接生成）。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="报错:生成失败")
    with _FrozenClock(_FROZEN_NOW):
        sched._schedule_retry(_FROZEN_YESTERDAY, 1, _FROZEN_NOW)
        with _RecordingPipelineCtx([(True, "ok", False)]) as fake:
            asyncio.run(sched._maybe_recover((4, 0), (8, 0)))

    assert fake.calls == []
    assert sched._retry is not None
    assert sched._retry["attempts_done"] == 1


def test_recover_skips_exhausted_retry(tmp_path: Path):
    """预算耗尽的报错记录：丢弃状态且不补生成（维持 e9c80cc 防重复语义）。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="报错:生成失败")
    with _FrozenClock(_FROZEN_NOW):
        sched._schedule_retry(_FROZEN_YESTERDAY, 3, _FROZEN_NOW)
        with _RecordingPipelineCtx([(True, "ok", False)]) as fake:
            asyncio.run(sched._maybe_recover((4, 0), (8, 0)))

    assert fake.calls == []
    assert sched._retry is None
    assert sched._storage.read_retry_state() is None


def test_recover_discards_stale_retry_state(tmp_path: Path):
    """日期不匹配的旧重试状态被丢弃。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    with _FrozenClock(_FROZEN_NOW):
        sched._schedule_retry("2026-01-01", 0, _FROZEN_NOW)
        with _RecordingPipelineCtx([(True, "ok", False)]) as fake:
            asyncio.run(sched._maybe_recover((4, 0), (8, 0)))

    assert sched._retry is None
    assert sched._storage.read_retry_state() is None
    # 旧状态被丢弃后，走常规补生成路径（而不是续跑旧日期的重试）
    assert fake.calls == [_FROZEN_YESTERDAY]


# ===== 推送双通道限额 =====


def test_push_error_then_diary_both_once(tmp_path: Path):
    """双通道独立限额：同日期先推失败消息，修好后仍可推一次日记。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="报错:生成失败", generation_time=1.0)

    with _FrozenClock(_FROZEN_NOW):
        asyncio.run(sched._push_safe(source="test"))
        assert sched._notifier.sent == [("failure", _FROZEN_YESTERDAY)]

        # 同状态重复推送 → 被失败通道限额拦住
        asyncio.run(sched._push_safe(source="test"))
        assert sched._notifier.sent == [("failure", _FROZEN_YESTERDAY)]

        # 手动重生成成功（写入更新的记录）→ 日记通道仍可推一次
        _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="生成成功", generation_time=2.0)
        asyncio.run(sched._push_safe(source="test"))
        assert sched._notifier.sent == [
            ("failure", _FROZEN_YESTERDAY),
            ("diary", _FROZEN_YESTERDAY),
        ]

        # 两通道都已推过 → 再推无动作
        asyncio.run(sched._push_safe(source="test"))
        assert len(sched._notifier.sent) == 2


def test_push_deferred_while_retry_pending(tmp_path: Path):
    """重试挂起时推送顺延：避免"刚推失败消息，重试就成功"。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="报错:生成失败")
    with _FrozenClock(_FROZEN_NOW):
        sched._schedule_retry(_FROZEN_YESTERDAY, 0, _FROZEN_NOW)
        asyncio.run(sched._push_safe(source="test"))

    assert sched._notifier.sent == []
    assert sched._storage.read_last_pushed_error_date() is None


def test_followup_push_after_retry_success(tmp_path: Path):
    """重试在 push_time 之后成功 → 立即补推日记一次。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="报错:生成失败")

    async def write_success(date: str) -> None:
        await _seed_diary_async(
            sched._storage, date, status="生成成功", generation_time=9.0
        )

    with _FrozenClock(_FROZEN_NOW):
        sched._schedule_retry(_FROZEN_YESTERDAY, 0, _FROZEN_NOW)
        with _RecordingPipelineCtx([(True, "ok", False)], success_writer=write_success):
            asyncio.run(sched._execute_retry())

    assert sched._retry is None
    assert sched._notifier.sent == [("diary", _FROZEN_YESTERDAY)]
    assert sched._storage.read_last_pushed_diary_date() == _FROZEN_YESTERDAY


def test_no_followup_push_before_push_time(tmp_path: Path):
    """重试在 push_time 之前成功 → 不立即推，交由调度器到点推送。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="报错:生成失败")

    async def write_success(date: str) -> None:
        await _seed_diary_async(
            sched._storage, date, status="生成成功", generation_time=9.0
        )

    early = datetime.datetime(2026, 9, 11, 6, 0, 0)
    with _FrozenClock(early):
        sched._schedule_retry(_FROZEN_YESTERDAY, 0, early)
        with _RecordingPipelineCtx([(True, "ok", False)], success_writer=write_success):
            asyncio.run(sched._execute_retry())

    assert sched._notifier.sent == []
    assert sched._storage.read_last_pushed_diary_date() is None


def test_push_now_bypasses_limit_and_marks_state(tmp_path: Path):
    """手动推送：显式意图不受限额拦截，但成功后写状态防自动重复。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="生成成功")
    with _FrozenClock(_FROZEN_NOW):
        # 模拟当日已自动推过日记
        sched._storage.write_last_pushed_diary_date(_FROZEN_YESTERDAY)
        ok, msg = asyncio.run(sched.push_now(_FROZEN_YESTERDAY))

    assert ok is True
    assert sched._notifier.sent == [("diary", _FROZEN_YESTERDAY)]
    assert "已推送" in msg


def test_push_now_reports_missing_record(tmp_path: Path):
    """手动推送：该日期无记录 → 明确回报，不静默。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    with _FrozenClock(_FROZEN_NOW):
        ok, msg = asyncio.run(sched.push_now(_FROZEN_YESTERDAY))

    assert ok is False
    assert "没有日记记录" in msg


def test_push_now_reports_unconfigured_notifier(tmp_path: Path):
    """手动推送：ntfy 未配置 → 明确回报。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    sched._notifier = NtfyNotifier(_make_ntfy_cfg(enabled=False))
    ok, msg = asyncio.run(sched.push_now(_FROZEN_YESTERDAY))

    assert ok is False
    assert "未启用" in msg


def test_push_now_error_record_uses_failure_channel(tmp_path: Path):
    """手动推送报错记录 → 走失败通道并写失败状态。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="报错:生成失败")
    with _FrozenClock(_FROZEN_NOW):
        ok, msg = asyncio.run(sched.push_now(_FROZEN_YESTERDAY))

    assert ok is True
    assert sched._notifier.sent == [("failure", _FROZEN_YESTERDAY)]
    assert sched._storage.read_last_pushed_error_date() == _FROZEN_YESTERDAY
    assert "失败消息" in msg


def test_push_skips_error_channel_when_send_on_failure_off(tmp_path: Path):
    """send_on_failure=false → 报错记录不推失败消息，也不写状态。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    sched._notifier = _RecordingNotifier()
    sched._cfg.ntfy.send_on_failure = False
    _seed_diary(sched._storage, _FROZEN_YESTERDAY, status="报错:生成失败")
    with _FrozenClock(_FROZEN_NOW):
        asyncio.run(sched._push_safe(source="test"))

    assert sched._notifier.sent == []
    assert sched._storage.read_last_pushed_error_date() is None


def test_status_exposes_retry_and_push_channels(tmp_path: Path):
    """/diary status 快照包含重试状态与双通道推送日期。"""
    sched = _make_scheduler(tmp_path, persist_state=False)
    with _FrozenClock(_FROZEN_NOW):
        sched._schedule_retry(
            _FROZEN_YESTERDAY, 1, _FROZEN_NOW + datetime.timedelta(minutes=20)
        )
        status = sched.get_status()

    assert _FROZEN_YESTERDAY in status["retry_state"]
    assert "1/3" in status["retry_state"]
    assert status["last_pushed_diary_date"] == "无"
    assert status["last_pushed_error_date"] == "无"


# ===== 独立运行入口（不依赖 pytest） =====


def _standalone_main() -> int:
    """用纯 unittest-style 跑一遍。"""
    import tempfile

    items = [
        (name, obj)
        for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    ]
    failed: list[tuple[str, str]] = []
    passed: list[str] = []
    tmp_root = Path(tempfile.mkdtemp(prefix="mai_diary_test_"))
    for name, fn in items:
        try:
            # pytest 的 tmp_path fixture 在独立运行时用一个统一临时目录代替
            sig = __import__("inspect").signature(fn)
            kwargs = {}
            if "tmp_path" in sig.parameters:
                kwargs["tmp_path"] = tmp_root / name
                kwargs["tmp_path"].mkdir(parents=True, exist_ok=True)
            fn(**kwargs)
            passed.append(name)
            print(f"  [PASS] {name}")
        except Exception as exc:
            import traceback as _tb

            failed.append((name, f"{type(exc).__name__}: {exc}"))
            print(f"  [FAIL] {name}: {type(exc).__name__}: {exc}")
            _tb.print_exc()
    print(f"\n{len(passed)} passed, {len(failed)} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(_standalone_main())
