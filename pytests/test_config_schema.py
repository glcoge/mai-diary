"""mai-diary 插件配置在 WebUI 的渲染契约测试（2026-09-14 全量审计后的护栏）。

与 narrative 侧同名测试同源（两插件是独立仓库，只能各存一份）：裸 ``dict`` /
``dict[str, X]`` / ``Any`` 注解会落到前端 ``plugin-config.tsx:178 FieldRenderer``
的 ``default`` 分支 → 单行 ``<Input type="text">``，JSON 值显示成 ``[object Object]``
且无法编辑；而 ``<Input>`` 按 HTML 规范会**剥离换行符**，所以默认值含 ``\\n``
的多行模板一旦用单行框渲染，保存即损坏。

三条不变量：
1. ``ui_type`` 落在前端支持的 8 个分支内；
2. 字段类型不得为 ``object``（除非是 ``list`` 对象数组，会展开成卡片行）；
3. 单行 ``text`` 字段的默认值不得含换行（应用 ``x-widget: textarea``）。

运行（项目根）：

    .venv/Scripts/python.exe -m pytest plugins/glcoge-mai-diary/pytests/test_config_schema.py -q
    .venv/Scripts/python.exe plugins/glcoge-mai-diary/pytests/test_config_schema.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from maibot_sdk.config import generate_plugin_config_schema

# 插件目录名含连字符，不能直接 import；config.py 无相对导入，单独加载即可
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.py"
_spec = importlib.util.spec_from_file_location("_diary_config_under_test", _CONFIG_PATH)
assert _spec is not None and _spec.loader is not None
_CONFIG = importlib.util.module_from_spec(_spec)
sys.modules["_diary_config_under_test"] = _CONFIG
_spec.loader.exec_module(_CONFIG)

# 前端 FieldRenderer 支持的全部 ui_type（缺一即退化为单行输入框）
_SUPPORTED_UI_TYPES = {
    "switch",
    "number",
    "slider",
    "select",
    "textarea",
    "password",
    "list",
    "text",
}


def _all_fields():
    schema = generate_plugin_config_schema(_CONFIG.MaiDiaryPluginConfig)
    return [
        (section_name, field_name, field)
        for section_name, section in schema.get("sections", {}).items()
        for field_name, field in (section.get("fields") or {}).items()
    ]


def _field_named(name: str):
    hits = [f for _, fname, f in _all_fields() if fname == name]
    assert hits, f"schema 中找不到字段 {name}"
    return hits[0]


# ===== 不变量 1：ui_type 必须被前端支持 =====


def test_all_ui_types_are_supported_by_frontend():
    bad = [
        f"{sec}.{name}={field.get('ui_type')!r}"
        for sec, name, field in _all_fields()
        if field.get("ui_type") not in _SUPPORTED_UI_TYPES
    ]
    assert not bad, f"出现前端不支持的 ui_type（会退化成单行输入框）: {bad}"


# ===== 不变量 2：不得映射为 object =====


def test_no_field_maps_to_object_type():
    bad = [
        f"{sec}.{name} (ui_type={field.get('ui_type')!r})"
        for sec, name, field in _all_fields()
        if field.get("type") == "object" and field.get("ui_type") != "list"
    ]
    assert not bad, f"字段类型退化为 object（WebUI 显示 [object Object]）: {bad}"


# ===== 不变量 3：单行框不得承载多行值 =====


def test_single_line_fields_have_no_newline_defaults():
    """<Input type="text"> 会剥离 \\n：默认值含换行的字段必须改用 textarea。"""
    bad = [
        f"{sec}.{name}"
        for sec, name, field in _all_fields()
        if field.get("ui_type") == "text"
        and isinstance(field.get("default"), str)
        and "\n" in field["default"]
    ]
    assert not bad, (
        f"以下字段用单行输入框但默认值含换行（保存即损坏），需加 x-widget=textarea: {bad}"
    )


# ===== 具体回归 =====


def test_sensitive_fields_are_masked():
    """topic / auth_token 在 WebUI 上打码（公共 ntfy.sh 下 topic 名等价于密码）。"""
    assert _field_named("topic")["ui_type"] == "password"
    assert _field_named("auth_token")["ui_type"] == "password"


def test_priority_is_select_not_free_text():
    """优先级必须是下拉，手填非法值会静默发出无效通知。"""
    field = _field_named("priority")
    assert field["ui_type"] == "select"
    assert set(field["choices"]) == {"min", "low", "default", "high", "urgent"}


def test_multiline_templates_use_textarea():
    """多行模板（目标聊天 / 自定义 prompt / MD 头尾）必须用多行框。"""
    for name in (
        "target_chats",
        "custom_prompt",
        "markdown_header_template",
        "markdown_footer_template",
        "body_footer_template",
        "truncate_suffix",
    ):
        assert _field_named(name)["ui_type"] == "textarea", name


# ===== 独立运行入口 =====

if __name__ == "__main__":
    fns = [
        (n, o) for n, o in sorted(globals().items())
        if n.startswith("test_") and callable(o)
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
