"""mai-diary 配置模型（PluginConfigBase 段式定义）。"""

from __future__ import annotations

from typing import ClassVar, List, Literal

from maibot_sdk import Field, PluginConfigBase


_DEFAULT_DIARY_PROMPT = (
    "你是'{bot_personality}'，现在是'{current_time}'，你要写一篇{target_length}字左右的日记。\n"
    "回顾昨天 04:00 到今天 04:00 的聊天记录：\n{timeline}\n\n"
    "要求：\n"
    "1. 开头必须是日期与天气：{date_with_weather}\n"
    "2. 像睡前随手写的感觉，轻松自然\n"
    "3. 回忆聊天内容，加入真实感受\n"
    "4. 有趣的事重点写，平淡的日子简单记录\n"
    "5. 偶尔加一两句小总结或感想\n"
    "6. 不要写成流水账，要有重点和感情色彩\n"
    "7. 用第一人称'我'来写\n\n"
    "书写风格：日常且口语化，平淡一些，遣词造句尽量简短。可以有个性。\n"
    "{style_desc}\n"
    "请注意不要输出多余内容（包括前后缀、冒号、引号、括号、表情等），只输出一段日记内容。"
    "{self_description_line}\n"
    "{narrative_status}"
    "日记内容:"
)


_DEFAULT_BRIEF_PROMPT = (
    "你是'{bot_personality}'，现在是'{current_time}'，你要写一篇简短的日记。\n"
    "回顾昨天 04:00 到今天 04:00 的聊天记录：\n{timeline}\n\n"
    "请用约 {target_length} 字、第三人称视角，记录今天的关键事件与心情。\n"
    "开头：{date_with_weather}\n"
    "书写风格：{style_desc}\n"
    "只输出日记正文，不要多余内容。{self_description_line}\n"
    "{narrative_status}"
    "日记内容:"
)


class PluginSection(PluginConfigBase):
    """插件基础设置。"""

    __ui_label__: ClassVar[str] = "插件"
    __ui_icon__: ClassVar[str] = "package"
    __ui_order__: ClassVar[int] = 0

    enabled: bool = Field(
        default=True,
        description="是否启用插件。关闭后所有定时、命令、API、Tool 都不生效。",
        json_schema_extra={"label": "启用插件", "order": 1},
    )
    config_version: str = Field(
        default="1.0.0",
        description="配置文件版本号，由 SDK 自动维护。",
        json_schema_extra={"label": "配置版本", "disabled": True, "order": 2},
    )
    admin_qq: List[str] = Field(
        default_factory=list,
        description="/diary 系列命令的 QQ 白名单。空列表 = 禁用所有命令。",
        json_schema_extra={
            "label": "管理员 QQ",
            "hint": '纯数字 QQ 号，例 ["123456"]',
            "item_type": "string",
            "placeholder": '["123456"]',
            "order": 10,
        },
    )


class ScheduleSection(PluginConfigBase):
    """定时任务设置。"""

    __ui_label__: ClassVar[str] = "定时"
    __ui_icon__: ClassVar[str] = "clock"
    __ui_order__: ClassVar[int] = 1

    generate_time: str = Field(
        default="04:00",
        description="每日触发生成的时间（24h，HH:MM）。",
        json_schema_extra={
            "label": "生成时间",
            "hint": "HH:MM 24 小时制",
            "placeholder": "04:00",
            "order": 1,
        },
    )
    push_time: str = Field(
        default="08:00",
        description="每日触发 ntfy 推送的时间（24h，HH:MM）。应晚于 generate_time。",
        json_schema_extra={
            "label": "推送时间",
            "hint": "HH:MM；晚于生成时间",
            "placeholder": "08:00",
            "order": 2,
        },
    )
    check_interval_seconds: int = Field(
        default=60,
        ge=5,
        le=3600,
        description="调度循环检查间隔（秒）。越小越精准但更耗 CPU。",
        json_schema_extra={
            "label": "检查间隔",
            "hint": "秒；建议 30-120",
            "order": 3,
        },
    )
    timezone_offset_hours: int = Field(
        default=8,
        ge=-12,
        le=14,
        description="时区偏移（小时，UTC+）。影响 generate_time / push_time 解释、日期归属与窗口划分。",
        json_schema_extra={
            "label": "时区偏移",
            "hint": "例：UTC+8 = 8、UTC-5 = -5",
            "order": 4,
        },
    )
    persist_state: bool = Field(
        default=True,
        description="是否在 data/ 持久化最近一次生成/推送日期，避免重启后重复。",
        json_schema_extra={"label": "持久化状态", "order": 5},
    )


class MessageSection(PluginConfigBase):
    """消息来源设置。"""

    __ui_label__: ClassVar[str] = "消息"
    __ui_icon__: ClassVar[str] = "message-square"
    __ui_order__: ClassVar[int] = 2

    filter_mode: Literal["all", "whitelist", "blacklist"] = Field(
        default="all",
        description="消息过滤模式。all=全部 / whitelist=仅 target_chats / blacklist=排除 target_chats。",
        json_schema_extra={
            "label": "过滤模式",
            "hint": "all=全部 / whitelist=仅列表 / blacklist=排除列表",
            "order": 1,
        },
    )
    target_chats: str = Field(
        default="",
        description=(
            "目标聊天列表（多行字符串，每行一个）。格式: group:群号 或 private:QQ号。"
            "filter_mode=all 时被忽略。"
        ),
        json_schema_extra={
            "label": "目标聊天",
            "hint": "每行一个，例 group:123456 或 private:1523640161",
            "placeholder": "group:123456\nprivate:1523640161",
            "rows": 4,
            "depends_on": "message.filter_mode",
            "depends_value": "whitelist",
            "order": 2,
        },
    )
    min_message_count: int = Field(
        default=5,
        ge=1,
        description="总消息数少于该值则跳过当日。",
        json_schema_extra={
            "label": "最少消息数",
            "hint": "总消息数（含 bot 与用户）；过少则跳过",
            "order": 3,
        },
    )
    min_messages_per_chat: int = Field(
        default=0,
        ge=0,
        description="单聊天消息数低于此值会被剔除。0 = 不过滤。",
        json_schema_extra={
            "label": "单聊最少消息",
            "hint": "过滤零碎水群；0=不过滤",
            "order": 4,
        },
    )
    per_message_max_chars: int = Field(
        default=200,
        ge=0,
        le=2000,
        description="单条消息最大字符数（超出截断）。0 = 不截断。",
        json_schema_extra={
            "label": "单条消息截断",
            "hint": "0-2000；0=不截断",
            "order": 5,
        },
    )


class SummarySection(PluginConfigBase):
    """总结生成设置。"""

    __ui_label__: ClassVar[str] = "总结"
    __ui_icon__: ClassVar[str] = "book-open"
    __ui_order__: ClassVar[int] = 3

    min_word_count: int = Field(
        default=250,
        ge=20,
        le=8000,
        description="日记最少字数。",
        json_schema_extra={"label": "最少字数", "hint": "20-8000", "order": 1},
    )
    max_word_count: int = Field(
        default=400,
        ge=20,
        le=8000,
        description="日记最多字数。必须 ≥ min_word_count。",
        json_schema_extra={"label": "最多字数", "hint": "20-8000；≥ 最少字数", "order": 2},
    )
    style: Literal["diary", "brief", "custom"] = Field(
        default="diary",
        description="日记风格：diary=日记体 / brief=简短记叙 / custom=自定义模板。",
        json_schema_extra={
            "label": "风格",
            "hint": "diary=日记体 / brief=简短 / custom=自定义",
            "order": 3,
        },
    )
    custom_prompt: str = Field(
        default="",
        description=(
            "自定义 prompt 模板（仅 style=custom 生效）。"
            "占位符: {current_time}, {bot_personality}, {style_desc}, {timeline}, "
            "{date_with_weather}, {target_length}, {self_description_line}"
        ),
        json_schema_extra={
            "label": "自定义 prompt",
            "hint": "占位符见描述",
            "rows": 10,
            "depends_on": "summary.style",
            "depends_value": "custom",
            "order": 4,
        },
    )
    use_bot_personality: bool = Field(
        default=True,
        description="是否注入主程序的 personality / expression 描述。",
        json_schema_extra={"label": "注入 bot 人格", "order": 5},
    )
    self_description: str = Field(
        default="",
        description="日记开头附加的自我形象描述。留空则不附加。",
        json_schema_extra={
            "label": "自我描述",
            "hint": "例：我是银发红瞳的狐妖",
            "rows": 2,
            "order": 6,
        },
    )


class LLMSection(PluginConfigBase):
    """LLM 调用设置。"""

    __ui_label__: ClassVar[str] = "LLM"
    __ui_icon__: ClassVar[str] = "cpu"
    __ui_order__: ClassVar[int] = 4

    text_model: str = Field(
        default="replyer",
        description="文本生成所用的 model task 名（需在主程序 model_config.toml 中存在）。",
        json_schema_extra={
            "label": "模型 task",
            "hint": "replyer / utils / planner 等",
            "placeholder": "replyer",
            "order": 1,
        },
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="生成温度。",
        json_schema_extra={"label": "温度", "hint": "0-2；日记建议 0.6-0.8", "order": 2},
    )
    truncate_tokens: int = Field(
        default=50000,
        ge=1000,
        le=200000,
        description=(
            "timeline 在送入 LLM 前的最大 token 估算值。"
            "超出后按句末截断。⚠️ host RPC 桥接层有 30s 硬上限，"
            "若 LLM 经常超时，可把此值调小。"
        ),
        json_schema_extra={
            "label": "截断 token 上限",
            "hint": "1000-200000；超长聊天时设小一些以免超时",
            "order": 3,
        },
    )
    timeout_seconds: int = Field(
        default=60,
        ge=10,
        le=3600,
        description=(
            "单次 LLM 调用的外层超时（秒）。⚠️ host RPC 桥接层有 30s 硬上限，"
            "本字段 > 30 时仍可能被 RPC 先切断。"
        ),
        json_schema_extra={
            "label": "LLM 超时",
            "hint": "秒；⚠️ host RPC 30s 硬上限",
            "order": 4,
        },
    )
    show_prompt: bool = Field(
        default=False,
        description="是否在 INFO 日志中打印 prompt 前 500 字（仅供调试）。",
        json_schema_extra={"label": "日志打印 prompt", "order": 5},
    )


class OutputSection(PluginConfigBase):
    """输出设置。"""

    __ui_label__: ClassVar[str] = "输出"
    __ui_icon__: ClassVar[str] = "file-text"
    __ui_order__: ClassVar[int] = 5

    base_dir: str = Field(
        default="data/diary",
        description="日记根目录（相对插件目录）。",
        json_schema_extra={
            "label": "根目录",
            "placeholder": "data/diary",
            "order": 1,
        },
    )
    write_markdown: bool = Field(
        default=True,
        description="是否写 Markdown 文件。开启后会写入 markdown/ 子目录。",
        json_schema_extra={"label": "写 Markdown", "order": 2},
    )
    write_json: bool = Field(
        default=True,
        description="是否写 JSON 文件（结构化记录，供 /diary v 等命令读取）。",
        json_schema_extra={"label": "写 JSON", "order": 3},
    )
    markdown_header_template: str = Field(
        default="# {date} 日记\n\n",
        description="Markdown 文件开头模板。可用占位符: {date}。",
        json_schema_extra={
            "label": "MD 开头模板",
            "rows": 2,
            "depends_on": "output.write_markdown",
            "depends_value": True,
            "order": 4,
        },
    )
    markdown_footer_template: str = Field(
        default="\n\n---\n\n*由 mai-diary 插件于 {generated_at} 生成*\n",
        description="Markdown 文件结尾模板。可用占位符: {generated_at}。",
        json_schema_extra={
            "label": "MD 结尾模板",
            "rows": 2,
            "depends_on": "output.write_markdown",
            "depends_value": True,
            "order": 5,
        },
    )


class NtfySection(PluginConfigBase):
    """ntfy 推送设置（每天 push_time 自动推送昨天生成的日记）。"""

    __ui_label__: ClassVar[str] = "ntfy 推送"
    __ui_icon__: ClassVar[str] = "bell"
    __ui_order__: ClassVar[int] = 6

    enabled: bool = Field(
        default=False,
        description=(
            "是否启用 ntfy 推送。⚠️ 启用后日记正文会离开本机（经 ntfy 服务器到手机），"
            "请确认接受此边界破坏。"
        ),
        json_schema_extra={"label": "启用 ntfy", "order": 1},
    )
    server: str = Field(
        default="https://ntfy.sh",
        description="ntfy 服务器地址。公共 ntfy.sh 免费层单消息约 4KB 限制。",
        json_schema_extra={
            "label": "服务器",
            "placeholder": "https://ntfy.sh",
            "order": 2,
        },
    )
    topic: str = Field(
        default="",
        description=(
            "ntfy 主题名（即手机端订阅的 topic）。⚠️ 公共 ntfy.sh 下 topic 名等价于密码，"
            "建议使用随机字符串（如 UUID），留空时即便 enabled=true 也不推送。"
        ),
        json_schema_extra={
            "label": "主题（topic）",
            "hint": "手机 ntfy 客户端订阅此 topic",
            "placeholder": "mai-diary-xxxxxxxx",
            "order": 3,
        },
    )
    auth_token: str = Field(
        default="",
        description="自建 ntfy 的访问令牌（Bearer Token）。公共 ntfy.sh 留空。",
        json_schema_extra={
            "label": "访问令牌",
            "hint": "自建服务才需要",
            "order": 4,
        },
    )
    priority: str = Field(
        default="default",
        description=(
            "通知优先级。取值：min / low / default / high / urgent。"
        ),
        json_schema_extra={
            "label": "优先级",
            "placeholder": "default",
            "order": 5,
        },
    )
    tags: List[str] = Field(
        default_factory=lambda: ["diary", "📔"],
        description="ntfy 标签列表（客户端可显示对应 emoji）。",
        json_schema_extra={
            "label": "标签",
            "hint": "逗号分隔的列表",
            "order": 6,
        },
    )
    title_template: str = Field(
        default="新日记  {date}",
        description="成功通知的标题模板。占位符：{date} {word_count} {weather}",
        json_schema_extra={
            "label": "成功标题模板",
            "rows": 1,
            "order": 7,
        },
    )
    failure_title_template: str = Field(
        default="❌ 日记生成失败  {date}",
        description="失败通知的标题模板。占位符：{date} {error}",
        json_schema_extra={
            "label": "失败标题模板",
            "rows": 1,
            "order": 8,
        },
    )
    body_footer_template: str = Field(
        default="\n\n—— mai-diary • {word_count}字",
        description=(
            "正文末尾追加的尾巴。占位符：{word_count}。设为空字符串可关闭。"
        ),
        json_schema_extra={
            "label": "正文尾巴模板",
            "rows": 2,
            "order": 9,
        },
    )
    max_body_chars: int = Field(
        default=2000,
        ge=200,
        le=20000,
        description=(
            "正文最大字符数。超出按句末截断。⚠️ 公共 ntfy.sh 总请求约 4KB 上限，"
            "中文字符 UTF-8 占 3 字节，建议 1500-3000。"
        ),
        json_schema_extra={
            "label": "正文最大字符数",
            "hint": "200-20000；公共 ntfy.sh 建议 1500-3000",
            "order": 10,
        },
    )
    truncate_suffix: str = Field(
        default="\n\n…（已截断，全文见本地文件）",
        description="正文被截断时附加的提示。",
        json_schema_extra={
            "label": "截断提示",
            "rows": 2,
            "order": 11,
        },
    )
    click_action: str = Field(
        default="",
        description=(
            "点击通知时打开的 URL。留空使用 ntfy 默认（打开 topic 页面）。"
            "可填 https:// 或 file:// 链接。"
        ),
        json_schema_extra={
            "label": "点击动作",
            "placeholder": "https://...",
            "order": 12,
        },
    )
    send_on_failure: bool = Field(
        default=True,
        description=(
            "日记生成失败时，push_time 是否推送失败通知（标题前缀 ❌）。"
            "设为 false 时失败不通知。"
        ),
        json_schema_extra={"label": "失败也推送", "order": 13},
    )
    timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=60,
        description="HTTP 请求超时（秒）。",
        json_schema_extra={
            "label": "HTTP 超时",
            "hint": "秒",
            "order": 14,
        },
    )


class NarrativeSection(PluginConfigBase):
    """剧本人设系统联动（mai-diary ↔ glcoge.mai-narrative 握手）。

    握手内容：
    - 会话分诊：剧本模式会话（mode_user_ids / mode_stream_ids）的日记，
      作者人格改从剧本「自我层」（锚定 identity + 心情 + 作息）读取，
      避免「聊天里是剧本人格、日记里是默认人格」的割裂。
    - 编年史写入：日记成功落盘后，幂等追加一条自我层编年史
      （scope=self，kind=diary；同一天重跑不重复写）。
    任何一步失败都只降级回旧逻辑，不影响日记生成与推送。
    """

    __ui_label__: ClassVar[str] = "剧本人设联动"
    __ui_icon__: ClassVar[str] = "link"
    __ui_order__: ClassVar[int] = 7

    enabled: bool = Field(
        default=True,
        description=(
            "是否尝试与剧本人设插件（glcoge.mai-narrative）握手。"
            "关闭后完全走旧逻辑（全局 personality + 不写编年史）。"
        ),
        json_schema_extra={"label": "启用联动", "order": 1},
    )
    api_timeout_seconds: int = Field(
        default=10,
        ge=2,
        le=60,
        description="跨插件 API 调用超时（秒）。握手失败自动降级，不影响日记主流程。",
        json_schema_extra={"label": "握手超时", "hint": "秒；2-60", "order": 2},
    )


class MaiDiaryPluginConfig(PluginConfigBase):
    """mai-diary 顶层配置。"""

    plugin: PluginSection = Field(default_factory=PluginSection)
    schedule: ScheduleSection = Field(default_factory=ScheduleSection)
    message: MessageSection = Field(default_factory=MessageSection)
    summary: SummarySection = Field(default_factory=SummarySection)
    llm: LLMSection = Field(default_factory=LLMSection)
    output: OutputSection = Field(default_factory=OutputSection)
    ntfy: NtfySection = Field(default_factory=NtfySection)
    narrative: NarrativeSection = Field(default_factory=NarrativeSection)


__all__ = [
    "PluginSection",
    "ScheduleSection",
    "MessageSection",
    "SummarySection",
    "LLMSection",
    "OutputSection",
    "NtfySection",
    "NarrativeSection",
    "MaiDiaryPluginConfig",
    "_DEFAULT_DIARY_PROMPT",
    "_DEFAULT_BRIEF_PROMPT",
]
