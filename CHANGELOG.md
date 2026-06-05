# 变更记录

## v0.6.1

**配对表情标签系统强化**

- 提示词升级为配对格式：要求 AI 每次情绪变化输出两个标签 `{emotion_自由}{emotion_立绘}`，自由标签（TTS 语气）+ 必选立绘标签（立绘切换）。同名时只写一个，确保立绘切换和语音语气同步
- `_build_tagged_text` 重构为按位置分组处理，同位置多标签输出堆叠格式 `[tag1][tag2]text`，自由标签不再被后一个覆盖丢失
- `_conf_schema.json` 默认提示词与 `DEFAULT_GALGAME_PROMPT` 完全同步，新增 emoji 输出禁止规则

**Bug 修复**

- 修复 TTS 不触发问题：AI 使用自由标签（如 `teasing`、`grin`）但不包含配置立绘标签时，`emotions` 为空导致 TTS guard 条件判定失败，改为 `if clean_text`
- 修复系统指令回复触发 TTS：`/reset`、`/new` 等以唤醒前缀开头的输入，LLM 回复不再触发语音朗读
- `_build_tagged_text` 空情绪列表时返回 `[neutral]text` 作为缺省
- 修复 Markdown 格式被 TTS 朗读：提示词新增禁止 `**粗体**`、`*斜体*`、`` `代码` ``、`#标题` 等格式标记
- 修复 `tts_enabled` 配置类型 `boolean` → `bool`（AstrBot 不支持 `boolean`）

**新功能**

- **BGM 背景音乐** — 设置页上传 mp3/wav/ogg 音频作为背景音乐，主页首次交互后自动循环播放
- **音量控制** — 语音朗读和 BGM 音量独立滑块调节，设置持久化到服务端 `prefs.json`，重启/清缓存不丢失
- **TTS 开关** — 插件配置页新增 `tts_enabled` 布尔开关，关闭后对话正常但不出声，Provider 配置保留
- **设置页改名** —「立绘管理」→「设置」，整合立绘素材 + BGM + 音量管理
- **会话自动恢复** — 重载插件后打开页面，自动找回最近一次有记录的对话，不再每次创建新会话
- **历史面板显示条数** — 新增 `history_limit` 配置，可限制历史面板最多显示最近 N 条消息，galgame backlog 风格

**其他修复**

- 修复浏览器录音 WAV 编码缺陷：Float32 样本缺少 ×32767 缩放导致音量极低，STT 插件判为静音
- 修复 `{emotion_ xxx}` 带空格的标签无法被正则匹配和剥离，宽松化正则支持 `emotion_` 与标签名之间的空格
- 修复模型空回复时前端对话框空白，回退显示省略号

## v0.6.0

**TTS 重构：MiniMax → Fish Audio 单次行内标签合成**

- 移除 MiniMax 直调引擎（`_minimax_tts`/`import aiohttp`）和 `minimax_tts` 配置段
- WebUI 聊天 TTS 直接调用 AstrBot provider（`self.context.provider_manager.inst_map.get`），绕过 pipeline 各阶段，避免 meme_manager 等插件误吞 `[xxx]` 方括号标签
- 插件配置新增 `tts_provider` 选择器，可直接选择 AstrBot 已注册的 TTS provider，未选择时回退全局默认
- LLM 回复按 `{emotion_xxx}` 标签边界分段，每段文本前拼接 Fish Audio 方括号情绪标签 `[xxx]`，**单次 API 调用**发送整段带标签文本，Fish Audio S2-Pro 按句子边界自动切换情绪
- 前端播放改为单个音频文件，消除旧分段 TTS 多文件重叠播放的 bug；立绘切换根据音频 duration 按字符位置比例 `setTimeout` 调度，与语音同步
- 新增 `tts_emotion_map` 配置：支持将 galgame 立绘情绪映射到 Fish Audio 情绪（如 `{"blush":"shy"}`），留空直接用标签本名
- 音频格式支持 wav/mp3 可选（`audio_format` 配置），mp3 模式用 ffmpeg 转码（~200KB/条 vs wav ~2MB），未安装 ffmpeg 自动回退

**自由情绪标签系统**

- 新增 `extract_all_emotions()`：匹配**所有** `{emotion_xxx}` 标签，拆分为 `known`（已配置的 7 种，给前端立绘切换）和 `all`（全部，给 TTS 拼 `[xxx]` 标签）
- LLM prompt 教 AI 除了必须的基础 7 种表情外，还可自由使用 `{emotion_excited}`、`{emotion_傲娇}`、`{emotion_whispering}` 等中英文自定义标签，Fish Audio S2-Pro 15000+ 自由文本描述全量可用
- 前端立绘只按已知 7 种切换，未知标签不影响显示

**移除 `[EMO:xxx]` 双标签系统**

- 删除 prompt 中的 `[EMO:xxx]` 指令，`{emotion_xxx}` 作为统一标签：立绘切换定位 + TTS 情绪输入
- `_capture_llm_response` 不再剥离 `[EMO:xxx]`；`_handle_emotion_strip` 精简，只做 `{emotion_xxx}` 剥离

**会话管理增强**

- 修复 Dashboard 重复空白 UMO 对话：`init_astrbot_conv` 创建前先查已有的 `get_curr_conversation_id`；`sync_sessions_to_db` 去掉 `create_if_not_exists`，对话不存在时重新 init
- 新增会话切换导航按钮（列表图标），替换原一次性模态框，可随时展开侧滑面板浏览和切换历史会话
- 每条会话卡片右上角新增 × 删除按钮，调用 `POST /session/delete` API 同时清理 AstrBot 对话、JSON 文件、关联音频
- 插件启动时自动清理无引用的空壳 session（history 为空 + conv 已不存在）
- `/new`、`/del`、`/reset` 指令完全同步 AstrBot 对话生命周期：`/new` 后从 AstrBot 读回新 conv_id，`/del` 后清空 conv_id 等 pipeline 自动重建，指令文本不记入 history
- `sync_conv_to_db` 更新前验证对话仍存在，避免向已删除对话写入

**音频文件管理**

- 音频孤儿清理：启动时扫描 `audio/` 目录，只保留被 session history 或收藏（`favorites.json`）引用的文件
- 会话删除时同步清理关联音频；`gc_sessions` 超期清理也一并清音频
- 收藏的语音受保护，永远不会被误删
- TTS 音频存入 `AUDIO_DIR`，支持历史面板回放和语音收藏

**其他修复**

- 过滤 meme_manager 产生的 `[IMAGE]xxx.jpg` 引用文本，防止显示在对话框
- 修复 `_build_tts_segments` 情绪错位 bug（`{emotion_xxx}` 在开头时后续分段全用错情绪）
- 修复 `ProviderManager` 无 `get_provider` 方法导致的 AttributeError → 改用 `inst_map.get`
- 修复 `sendMessage`/`notifyRapidAction` 中多余/缺失 `}` 导致的 SyntaxError 页面全紫

## v0.5.5

- **分段情感 TTS** — 新增 MiniMax 直调引擎，galgame 按 LLM 输出的 `{emotion_xxx}` 标签位置自动切分文本，每段独立调用 MiniMax API 合成不同情绪的语音。前端打字机播放时逐段触发对应情感的语音。不配 `minimax_tts.api_key` 则整个模块不启动，零影响 Single/VRM 模式
- **LLM 情绪标记提示** — `DEFAULT_GALGAME_PROMPT` 新增规则教会 LLM 同时输出 `[EMO:xxx]`（供 TTS 插件消费）和 `{emotion_xxx}`（供 galgame 立绘切换），双轨并行互不干扰

## v0.5.4

- **历史面板角色头像** — AI 消息左侧显示圆形头像。立绘管理页新增头像槽位，上传 PNG 后自动注册到 `history_avatar` 配置。不上传则不显示
- **历史语音回放** — 历史面板中每条有 TTS 语音的 AI 回复旁显示 ▶ 按钮，点击即可播放。音频永久存储到 `data/plugin_data/.../audio/`，不随会话清理丢失
- **语音收藏** — 新增收藏页面（顶部 ❤ 入口），可收藏 AI 语音和对应文本。数据存于 `favorites.json`，独立于会话，`/reset`/`/new` 不丢失。支持按时间线浏览、播放、取消收藏。页面风格与历史面板统一暖色毛玻璃
- **音频格式兼容** — `web_handler.py` 新增 `audio/` 路径路由，收藏和历史回放直接通过本地 HTTP 取文件，无延迟

## v0.5.3

- **TTS 标签冲突处理** — `_capture_llm_response` 新增剥离 `[EMO:xxx]`（TTS 插件标签）；`_api_send` 新增剥离 MiniMax 语音控制符 `(inhale)`/`<#0.6#>`（表现力标签），防止前端对话框出现无关字符。配合 v0.5.2 的 `{emotion_xxx}` 剥离构成完整两插件共存方案
- **combine_messages 兼容性** — 明确声明不建议与消息合并/防抖插件一同使用。AstrBot 内置 `session_plugin_config` 可对 webchat 会话禁用指定插件。README 添加醒目警告
- **HTTP 代理超时** 120s → 300s，消除慢 LLM 请求断连
- **点击快进** — 打字机播放中点击对话框，文字 0.2s 弹入全量显示 + 立绘 0.6s 淡入切至最终表情，还原 galgame 快进手感
- **轻戳角色** — 空闲状态下在背景/角色区快速点击 5 次，AI 收到 `(戳了戳)` 主动对话，模拟戳屏互动
- **重播语音** — 重播按钮现在同时回放 TTS 语音

## v0.5.2

- **TTS 情绪标签剥离** — 新增 `on_decorating_result(priority=1)` 钩子，在 TTS 插件合成语音前从消息链中剥离 `{emotion_xxx}` 标签，避免标签被当作文字读出。情绪数据缓存到 session 供 `_api_send` 使用
- **音频格式自动检测** — 用文件 magic bytes（RIFF/ID3/OggS/fLaC/ftyp）替代后缀名判断 MIME 类型。webchat 适配器总是存为 `.wav` 后缀，但实际格式可能是 mp3，此前会导致浏览器播放失败
- **打字机速度可配置** — 新增 `typewriter_speed` 配置项（`_conf_schema.json`），默认 60ms/字，支持 10~200 范围
- **重播按钮升级** — `replayLastResponse` 现在同时重放 TTS 语音，`lastReplyData` 新增 audio 字段，每次新回复覆盖旧数据不堆积
- **修复插件载入错误** — `_conf_schema.json` 类型名 `integer` → `int`，兼容 AstrBot schema 校验

## v0.5.1

- **TTS 语音朗读** — `_push_through_pipeline` 新增 `record` 类型监听，自动从管道 back_queue 捕获音频并 base64 编码返回前端。配合任意 AstrBot TTS 插件（如 `astrbot_plugin_tts_emotion_router`）即可实现语音朗读，不安装 TTS 插件时静默降级
- **对话框重播按钮** — 对话框新增重播按钮（旋转箭头图标），点击可重播上次 AI 回复的完整打字机动画 + 表情切换
- **会话恢复功能** — 新增 `GET /session/list` API 与前端会话选择器弹窗。清除浏览器缓存或换设备后，可浏览磁盘上的历史会话列表并选择恢复，同时支持 `?sid=xxx` URL 参数直达
- **JSON 过滤优化** — 修复 `startswith("{")` 暴力过滤误伤 `{emotion_xxx}` 表情标签导致整个回复为空的 bug，改用 `json.loads` 精确校验纯 JSON 片段
- **元数据更新** — 修正 `metadata.yaml` 描述，移除已废弃的分层立绘动画说明，补充 TTS 和会话恢复
- **README 重写** — 标注 VRM 开发中状态，调整文档结构突出快速开始，补充遗漏特性（JWT 认证、会话双向同步、资产迁移等）

## v0.5.0

- **VRM 3D 模式** — `sprite_mode` 新增 `vrm` 选项，使用 Three.js + three-vrm 渲染 3D 动漫角色
- **原生动画** — VRM 自动眨眼、视线跟踪鼠标、表情 blend shape 切换、骨骼呼吸
- **零成本建模** — 支持 VRoid Studio（免费）导出的 .vrm 模型，VRoid Hub 数十万免费模型
- **前端依赖变更** — 新增 Three.js + three-vrm CDN 引入（~800KB，浏览器缓存后 0 开销）
- **破坏性变更** — 删除整个 Canvas 分层立绘引擎；`sprite_mode` 从 `layered` 变为 `vrm`；`expressions_blink` 和旧 `layers` 配置结构移除
- **迁移** — v0.4 用户升级后需将 `sprite_mode` 从 `layered` 改为 `vrm`，并准备 `.vrm` 模型文件替代原 PNG 表情
- 新增 `vrm_model` 配置项 + `_api_config` 返回 VRM 文件路径
- `_resolved_assets` 新增 .vrm 文件自动检测
- Single 模式完全不变，无迁移成本

## v0.4.0

- **Layered 模式重写** —— 废弃多层 PNG 叠加，改为 Canvas 单图逐行正弦形变渲染
- **眨眼系统** —— 每情绪可选 `_blink` 闭眼变体图，真正换图眨眼（替换旧的 scaleY 压扁方案）
- **呼吸动画升级** —— 从 JS 多频正弦波改为纯 CSS `scaleY` + `scaleX` 挤压拉伸（`transform-origin: bottom center`）
- **表情切换渐变** —— Canvas opacity fade out → 换源 → fade in（300ms 过渡）
- **素材简化** —— 不再需要拆分 body/head/hair/mouth 等图层，一张全身立绘即可
- 删除 `LAYER_KEYS`、口型同步、多层动画引擎（净减 81 行代码）
- 后端新增 `expressions_blink` 自动检测与 API 返回
- Single 模式完全不变

## v0.3.0

- **独立 WebUI 端口** — 插件内置 HTTP 服务器，在独立端口提供完整 WebUI
- **管道全集成** — 所有消息经 webchat 管道分发，指令和语音走管道、记忆/感知/安全全栈生效
- **AstrBot 指令全兼容** — `/help /reset /new` 等所有已注册指令正常运行
- **语音输入** — 浏览器麦克风录音为 WAV，经管道 STT 插件转文字后发送
- **立绘位置可调** — 新增 `sprite_bottom`、`sprite_left` 配置项，自由调整角色站位
- **立绘缩放** — 新增 `sprite_scale` 配置项，CSS `scale` 变换
- **批量删除** — 立绘管理页多选文件一键删除
- **资产迁移** — assets 目录移至 `data/plugin_data/`，插件更新不丢用户图片；`.migrated` 标记防重复搬迁
- **对话历史面板** — 内建聊天记录查看，气泡式展示，背景色自适应
- **JWT 代理认证** — 所有 API 请求通过代理自动附带 JWT Bearer 令牌
- 移除 Dashboard 内嵌 / Bridge SDK / SSE 依赖
- `user-select: auto`，`localStorage` 正常工作

## v0.2.4

- **立绘管理页按模式分区** —— Single / Layered 分区独立展示所需文件清单，当前模式高亮
- **槽位上传自动重命名** —— 从表情/图层槽位上传的文件自动存为标准名（如 `happy.png`），无需手动改名
- **支持自定义情绪** —— 新增 `custom_emotions` 配置字段（JSON），可自由添加额外情绪标签
- 全面重写 README：详述两种模式差异、文件需求、表情系统、命名约定

## v0.2.3

- **立绘管理页面** —— 浏览器内拖拽上传 / 预览 / 删除 PNG，自动匹配情绪和图层映射，主页右上角齿轮入口
- **配置页提示优化** —— 表情/分层立绘字段标注「留空=自动」，引导使用管理页面上传，无需逐个填写
- 新增 `POST /assets/upload`、`POST /assets/delete`、`POST /assets/batch` API
- 修复管理页图片预览不显示的问题

## v0.2.2

- **对话接入 AstrBot 消息系统** —— Galgame 对话自动写入 `conversations` 和 `platform_message_history` 表，Dashboard `对话管理` 页面可查看/编辑/导出
- 旧会话 JSON 文件自动迁移至数据库，无缝兼容

## v0.2.1

- **立绘路径自动检测** —— 按命名约定放入 assets 目录即可零配置使用
- 新增 `/assets/list` API

## v0.2.0

- 前端全面改造为 Galgame 沉浸式 UI（三层结构、毛玻璃对话框、标签、底划线输入框）
- 角色人格改用 AstrBot 内置 Persona 系统
- 会话持久化（磁盘 + localStorage），可配置保留天数
- 场景背景图配置、`/galgame` 指令
- 插件名改为 `astrbot_plugin_galgame_web`

## v0.1.0

- 首次发布，基础 Galgame 交互功能
