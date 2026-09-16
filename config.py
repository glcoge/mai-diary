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
        description=(
            "每日触发生成的时间（24h，HH:MM）。它**同时决定日记时间窗的切割小时**："
            "默认 04:00 → 窗口为 [昨日 04:00, 今日 04:00)。"
            "⚠️ 改成其他小时时，内置 prompt 里「回顾昨天 04:00 到今天 04:00」的"
            "说明不会自动跟随，请配合 style=custom 自定义 prompt。"
        ),
        json_schema_extra={
            "label": "生成时间",
            "hint": "HH:MM 24 小时制；同时决定时间窗切割小时",
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
        description=(
            "调度循环的兜底睡眠间隔（秒）。⚠️ 正常路径下调度器会算出最近的"
            "generate/push/retry 时刻并精确唤醒，调小本值**不会**提高触发精度；"
            "它只在无候选动作或发生异常时兜底生效。"
        ),
        json_schema_extra={
            "label": "检查间隔",
            "hint": "秒；仅在无候选/异常时兜底，不影响触发精度",
            "order": 3,
        },
    )
    timezone_offset_hours: int = Field(
        default=8,
        ge=-12,
        le=14,
        description=(
            "时区偏移（小时，UTC+）。影响 generate_time / push_time 解释、"
            "日期归属与窗口划分。"
            "⚠️ 宿主机系统时区已正确设置为目标时区、或系统时区为 UTC 时，"
            "本项不生效（引擎直接信墙钟）。Docker 容器常注册为 UTC，"
            "此时填 8 不会得到 UTC+8，请直接改容器时区。"
        ),
        json_schema_extra={
            "label": "时区偏移",
            "hint": "例：UTC+8 = 8、UTC-5 = -5；⚠️ 系统为 UTC 时不生效",
            "order": 4,
        },
    )
    persist_state: bool = Field(
        default=True,
        description=(
            "已废弃（保留兼容）：防重复幂等判定始终生效，不再受此开关控制。"
            "可忽略，建议保持默认。"
        ),
        json_schema_extra={
            "label": "持久化状态（已废弃，可忽略）",
            # 死字段：代码里零读取。标 hidden 避免用户在配置页误以为它能控制什么
            "hidden": True,
            "order": 5,
        },
    )


class RetrySection(PluginConfigBase):
    """软失败退避重试设置。

    仅对**软失败**生效（LLM 返回空 / LLM 超时 / 生成异常）；
    「消息数量不足」属硬失败——时间窗已闭合，重试不会改变结果，不重试。
    手动 `/diary gen` 触发的失败也不进入重试队列（用户在场，可自行决定是否再跑）。
    """

    __ui_label__: ClassVar[str] = "重试"
    __ui_icon__: ClassVar[str] = "rotate-ccw"
    __ui_order__: ClassVar[int] = 8

    enabled: bool = Field(
        default=True,
        description="是否启用软失败退避重试。关闭后行为与旧版本一致（失败即放弃）。",
        json_schema_extra={"label": "启用重试", "order": 1},
    )
    max_attempts: int = Field(
        default=3,
        ge=0,
        le=10,
        description="重试次数上限（不含首次尝试）。3 = 最多再试 3 次，成功即停止。",
        json_schema_extra={"label": "最大重试次数", "hint": "不含首次；0=不重试", "order": 2},
    )
    base_delay_minutes: int = Field(
        default=10,
        ge=1,
        le=1440,
        description="退避基数（分钟）。第 n 次重试前等待 base × 2^(n-1)，默认 10 → 10/20/40 分钟。",
        json_schema_extra={"label": "退避基数", "hint": "分钟；默认 10 → 10/20/40", "order": 3},
    )
    max_delay_minutes: int = Field(
        default=120,
        ge=1,
        le=10080,
        description="单次退避上限（分钟），防止基数调大后等待过久或跨天。",
        json_schema_extra={"label": "退避上限", "hint": "分钟", "order": 4},
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
            "whitelist（仅列表内）与 blacklist（排除列表内）模式下都需要填写；"
            "filter_mode=all 时被忽略。"
        ),
        json_schema_extra={
            "label": "目标聊天",
            "hint": "每行一个，例 group:123456 或 private:1523640161；"
                   "whitelist 与 blacklist 模式均需填写",
            "placeholder": "group:123456\nprivate:1523640161",
            # str 默认渲染成单行 <Input>：多行内容会被挤成一行，保存即损坏配置
            "x-widget": "textarea",
            "rows": 4,
            # 2026-09-16 删除 depends_on / depends_value：前端只在
            # dashboard/src/lib/plugin-api/types.ts 有类型定义，无组件读取，
            # 是死元数据（原值 "whitelist" 还会让人误以为 blacklist 下会隐藏本字段）
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
        description=(
            "目标字数下限。与 max_word_count 一起，在区间内随机取一个目标值写进 prompt。"
            "⚠️ 不是硬性下限：模型写少了不会补写或重生成。"
        ),
        json_schema_extra={"label": "最少字数", "hint": "20-8000；仅作 prompt 目标值", "order": 1},
    )
    max_word_count: int = Field(
        default=400,
        ge=20,
        le=8000,
        description=(
            "目标字数上限，**这一条是硬上限**：超出会按句末截断。"
            "必须 ≥ min_word_count（更小时自动取 min_word_count）。"
        ),
        json_schema_extra={"label": "最多字数", "hint": "20-8000；≥ 最少字数，超出截断", "order": 2},
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
            "自定义 prompt 模板。⚠️ style=custom 与 style=brief 时都会生效"
            "（brief 下会覆盖内置简短模板）；style=diary 时忽略本项。"
            "可用占位符: {date}, {timeline}, {date_with_weather}, {target_length}, "
            "{bot_personality}, {style_desc}, {self_description_line}, {current_time}, "
            "{narrative_status}"
            "（{narrative_status} 仅在剧本人设握手成功时非空；"
            "未识别的占位符会被替换成空串）"
        ),
        json_schema_extra={
            "label": "自定义 prompt",
            "hint": "custom 与 brief 风格均生效；占位符见描述",
            "x-widget": "textarea",
            "rows": 10,
            # 2026-09-16 删除 depends_on / depends_value（死元数据，前端无组件读取）
            "order": 4,
        },
    )
    use_bot_personality: bool = Field(
        default=True,
        description=(
            "是否注入主程序的 personality / expression 描述。"
            "⚠️ 关闭后还有两个连带影响：① 不再识别 bot 自身消息"
            "（时间线里 bot 发言显示为昵称而非「我」，bot_messages 统计记 0）；"
            "② 跳过剧本人设联动（日记不再使用剧本自我层人格）。"
        ),
        json_schema_extra={"label": "注入 bot 人格", "hint": "关闭会连带影响 bot 发言识别与剧本联动", "order": 5},
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
        default="",
        description=(
            "文本生成所用的**模型名**（不是任务名）。须与 WebUI「模型列表」中已注册的"
            "模型名完全一致；留空则用主程序默认模型。"
            "⚠️ 填任务名（如 replyer）会报「未找到名为 'X' 的模型」——"
            "宿主只按模型名查找。"
            "⚠️ 推理模型（glm-5.x 等默认开思考）跑日记长文本会返回空 choices，"
            "请先在该模型的 extra_params 配 {thinking = {type = \"disabled\"}}。"
        ),
        json_schema_extra={
            "label": "模型名",
            "hint": "填模型名而非任务名，如 glm-5.1；留空=用默认模型。"
                   "推理模型请先关闭思考模式",
            "placeholder": "glm-5.1",
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
            "timeline 在送入 LLM 前的最大 token 估算值，超出后按句末截断。"
            "⚠️ host RPC 桥接层有 30s 硬上限，若 LLM 经常超时，优先调小此值"
            "（调小 timeout_seconds 无效）。"
            "⚠️ 若报「模型返回空内容」或「choices 为空」，多半是所选模型默认开启"
            "思考模式（如 glm-5.x），请在该模型的 extra_params 关闭思考，"
            "或改用非推理模型。本插件输出侧 max_tokens 固定 4096，不可配置。"
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
            "单次 LLM 调用的外层超时（秒）。"
            "⚠️ host RPC 桥接层有 30s 硬上限：本字段超过 30 时**不起作用**，"
            "实际生效上限就是 30s。调小它只是让客户端更早放弃，并不解决超时根因 ——"
            "应改调小 truncate_tokens，或换用非推理模型。"
        ),
        json_schema_extra={
            "label": "LLM 超时",
            "hint": "秒；⚠️ 超过 30 无效（RPC 先切断）",
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
    # 2026-09-16 移除 write_json：全仓从未读取该字段，JSON 始终写入
    # （/diary ls 与 /diary v 依赖它）。留着只会让人以为关掉能省盘。
    markdown_header_template: str = Field(
        default="# {date} 日记\n\n",
        description="Markdown 文件开头模板。可用占位符: {date}。",
        json_schema_extra={
            "label": "MD 开头模板",
            # 默认值含 \n\n：单行 <Input> 会把换行挤掉，保存即损坏
            "x-widget": "textarea",
            "rows": 2,
            # 2026-09-16 删除 depends_on / depends_value（死元数据）
            "order": 4,
        },
    )
    markdown_footer_template: str = Field(
        default="\n\n---\n\n*由 mai-diary 插件于 {generated_at} 生成*\n",
        description="Markdown 文件结尾模板。可用占位符: {generated_at}。",
        json_schema_extra={
            "label": "MD 结尾模板",
            # 同上：默认值以 \n\n 开头，单行输入框会吞掉换行
            "x-widget": "textarea",
            "rows": 2,
            # 2026-09-16 删除 depends_on / depends_value（死元数据）
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
            # 公共 ntfy.sh 下 topic 名等价于密码 → WebUI 打码显示
            # （仅界面遮蔽，config.toml 仍是明文，与 MaiBot 现有凭据存储一致）
            "x-widget": "password",
            "order": 3,
        },
    )
    auth_token: str = Field(
        default="",
        description="自建 ntfy 的访问令牌（Bearer Token）。公共 ntfy.sh 留空。",
        json_schema_extra={
            "label": "访问令牌",
            "hint": "自建服务才需要",
            "x-widget": "password",
            "order": 4,
        },
    )
    priority: Literal["min", "low", "default", "high", "urgent"] = Field(
        default="default",
        description="通知优先级。取值：min / low / default / high / urgent。",
        json_schema_extra={
            "label": "优先级",
            "hint": "min / low / default / high / urgent",
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
            # 默认值以 \n\n 开头：单行 <Input> 会剥离换行，保存即损坏
            "x-widget": "textarea",
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
            "x-widget": "textarea",
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
    retry: RetrySection = Field(default_factory=RetrySection)


__all__ = [
    "PluginSection",
    "ScheduleSection",
    "RetrySection",
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
