"""diary 命令开关 gate + 已移除配置项测试（2026-09-16 B6/B7 + C①）。

- **B7 命令补开关判断**：`plugin.enabled=false` 时，`on_load` 会早退
  （`_scheduler` 保持 None），但**命令是类上的方法，仍会被调用**。
  此前 `/diary gen` 会直接执行 `self._scheduler.trigger_now(...)`
  → AttributeError。现在禁用时只保留 help，其余命令回一条提示。
- **B6** `[output].write_json` 已从 config 移除（全仓从未读取，JSON 始终写入）。

运行（项目根）：

    .venv/Scripts/python.exe -m pytest plugins/glcoge-mai-diary/pytests/test_command_gates.py -q
    .venv/Scripts/python.exe plugins/glcoge-mai-diary/pytests/test_command_gates.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_SYNTH = "_diary_cmd_gate_probe"


def _load(rel_name: str, file_path: Path) -> types.ModuleType:
    full = f"{_SYNTH}.{rel_name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, str(file_path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


# 插件目录名含连字符，挂到合法标识符的合成包下；utils 必须真实加载
# （services/diary/* 都 `from ...utils import get_logger`），services 可以是空壳包
pkg = types.ModuleType(_SYNTH)
pkg.__path__ = [str(PLUGIN_ROOT)]  # type: ignore[attr-defined]
sys.modules[_SYNTH] = pkg
for sub in ("services", "services.diary"):
    mod = types.ModuleType(f"{_SYNTH}.{sub}")
    mod.__path__ = [str(PLUGIN_ROOT / sub.replace(".", "/"))]  # type: ignore[attr-defined]
    sys.modules[f"{_SYNTH}.{sub}"] = mod
_load("utils", PLUGIN_ROOT / "utils" / "__init__.py")
_CONFIG = _load("config", PLUGIN_ROOT / "config.py")
_PLUGIN = _load("plugin", PLUGIN_ROOT / "plugin.py")

MaiDiaryPlugin = _PLUGIN.MaiDiaryPlugin
MaiDiaryPluginConfig = _CONFIG.MaiDiaryPluginConfig


class _Logger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _FakeScheduler:
    """记录 trigger_now 调用的假调度器。"""

    def __init__(self):
        self.triggered: list = []

    async def trigger_now(self, *args, **kwargs):
        self.triggered.append((args, kwargs))
        return True, "ok"


def _make_plugin(enabled=True, admin_qq=("10001",)):
    """构造 plugin 实例；``_scheduler`` 按 on_load 早退语义设为 None（禁用时）。"""
    plugin = MaiDiaryPlugin.__new__(MaiDiaryPlugin)
    # SDK 的 config 是只读 property，直接赋值底层实例
    plugin._plugin_config_instance = SimpleNamespace(
        plugin=SimpleNamespace(enabled=enabled, admin_qq=list(admin_qq)),
        # _cmd_gen 成功后会回传文件路径，需要 output.base_dir
        output=SimpleNamespace(base_dir=tempfile.mkdtemp()),
    )
    sent: list = []

    class _Send:
        async def text(self, text, stream_id):  # noqa: ANN001
            sent.append(text)

    # SDK 的 ctx / config 都是只读 property，直接赋值底层实例
    # （属性名见 maibot_sdk/plugin.py:69 与 :73）
    plugin._ctx = SimpleNamespace(send=_Send(), logger=_Logger())
    plugin._scheduler = _FakeScheduler() if enabled else None
    plugin.sent = sent
    return plugin


def _run_cmd(plugin, sub: str) -> tuple:
    return asyncio.run(
        plugin.handle_diary(
            matched_groups={"sub": sub}, stream_id="s1", user_id="10001"
        )
    )


# ===== B7：禁用时只保留 help =====


def test_help_still_works_when_disabled():
    plugin = _make_plugin(enabled=False)
    ok, _, _ = _run_cmd(plugin, "help")
    assert ok is True
    assert plugin.sent, "help 应当有输出"


def test_bare_command_is_treated_as_help_when_disabled():
    """裸 /diary 等同 help，禁用时也应可用。"""
    plugin = _make_plugin(enabled=False)
    ok, _, _ = _run_cmd(plugin, "")
    assert ok is True
    assert plugin.sent


def test_gen_rejected_when_disabled():
    """关键：禁用时调 gen 必须被拦下，不得碰 _scheduler（此前会 AttributeError）。"""
    plugin = _make_plugin(enabled=False)
    ok, reason, _ = _run_cmd(plugin, "gen 2026-09-15")
    assert ok is True
    assert reason == "plugin disabled"
    assert any("已禁用" in text for text in plugin.sent)


def test_other_commands_rejected_when_disabled():
    """push / ls / v / status 全部拦下。"""
    for sub in ("push", "ls", "v 2026-09-15", "status"):
        plugin = _make_plugin(enabled=False)
        _, reason, _ = _run_cmd(plugin, sub)
        assert reason == "plugin disabled", sub


def test_commands_work_when_enabled():
    """启用时不应走禁用分支（gen 应真的到达 scheduler）。"""
    plugin = _make_plugin(enabled=True)
    _, reason, _ = _run_cmd(plugin, "gen 2026-09-15")
    assert reason != "plugin disabled"
    assert plugin._scheduler.triggered, "启用时 gen 应到达调度器"


def test_non_admin_rejected_regardless():
    """非管理员即使在启用态也被拒（既有行为，防止 gate 改动误伤）。"""
    plugin = _make_plugin(enabled=True, admin_qq=())
    ok, reason, _ = _run_cmd(plugin, "ls")
    assert ok is False
    assert reason == "no admin"


# ===== B6：write_json 已移除 =====


def test_write_json_removed_from_config():
    config = MaiDiaryPluginConfig()
    assert not hasattr(config.output, "write_json"), "write_json 应已从 config 移除"
    assert hasattr(config.output, "write_markdown")


def test_markdown_templates_still_present():
    """移除操作不应误伤相邻字段。"""
    config = MaiDiaryPluginConfig()
    assert hasattr(config.output, "markdown_header_template")
    assert hasattr(config.output, "markdown_footer_template")


# ===== 独立运行入口 =====

if __name__ == "__main__":
    fns = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  [PASS] {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [FAIL] {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed} passed, {failed} failed")
    sys.exit(0 if not failed else 1)
