# 变更记录

## v0.7.13

**安全加固**

- 独立 WebUI 代理改为插件 API 精确白名单，不再转发任意 AstrBot Dashboard API。
- 无 WebUI 密码时自动仅监听 `127.0.0.1`；设置独立密码后保留局域网访问能力。
- 修复会话 ID、素材 key、音频文件名的路径穿越和越界删除风险。
- 修复会话摘要与 BGM 文件名导致的持久化 XSS，以及未校验来源的跨窗口 API 消息代理。
- 增加原子登录限速、同源 POST 校验、安全响应头、有界连接/代理并发、请求大小限制和短期代理令牌。
- 同一会话发送改为串行处理，语音暂存文件在请求结束后清理。
- 修复新会话状态清理、最近会话恢复、首次 BGM 播放和旧收藏被上限截断的问题。
- 新增安全回归测试，覆盖代理白名单、认证、路径边界、输入上限和前端渲染。

## v0.7.12

**会话生命周期重构**

- **延迟创建 AstrBot 对话** — 新建会话不再立即调用 `init_astrbot_conv` 在数据库创建 conversation 记录，改为仅设置 `umo`。用户发送第一条消息并收到 AI 回复后，才通过 pipeline 自动补全 `conv_id`。不发消息就不会在 AstrBot 数据库产生任何记录，从根源消灭空白会话累积。
- **空白会话复用** — `_api_session_init` 新增 `_find_blank_session()`，新建会话前优先查找已有空白会话（无 history）复用，不再每次打开页面都创建新会话文件。
- **sync_sessions_to_db 修复** — 启动时不再误删延迟初始化的空白会话（有 `umo` 但无 history 的会话被正确保留）。仅删除既无 `history` 又无 `umo` 的真正死会话。磁盘清理同步检查 `umo` 字段。
- **llm_provider 配置生效** — `_push_through_pipeline` 现在读取插件配置中的 `llm_provider` 并传入 pipeline。用户不选时传 `None` 走全局默认，选了则覆盖。此前该配置项始终为 `None`，实际未生效。
- `_send_extract_emotions` 中将 `conv_id` 同步从后台任务（`ensure_future`）改为同步 `await`，并移出锁块避免死锁。

## v0.7.11

- **可展开输入框** — 发送按钮旁新增 ↙↗ 按钮，点击展开至 320px 方便长篇输入，再点恢复单行。展开时自动聚焦。placeholder 提示 Enter 发送 / Shift+Enter 换行
- **空白会话复用** — 新建对话时自动查找已有空白会话并切换，不再无脑创建新会话。空白会话不显示删除按钮，避免 Dashboard 内嵌页删除崩白
- 修复历史面板打开时不自动滚到底部
- 修复麦克风错误提示在独立 WebUI 误显 Dashboard 专属文案
- 修复展开按钮连点触发快速点击检测导致输入框卡死
- 修复 AI 拼错 emotion 前缀（如 `{emusement_happy}`）导致标签漏到前端显示

## v0.7.10

## v0.7.9

**TTS 并行修复与可靠性提升**

- **TTS 真正并行** — 修复 `get_audio()` 并非 async 导致的并发失效。空 emotion 也切句并行，3 句从串行 6s→并行 2s
- **emotion 强制句首** — 切句后所有 emotion 标签 force 到位置 0，确保 Fish Audio 正确识别
- **Semaphore(5) 并发控制** — 限制同时最多 5 路 TTS 调用，避免被 Fish Audio 限流
- **提示词英文强化** — "无论中英文此规则绝对强制"，AI 英文回复不再遗漏 emotion 标签
- **兜底过滤拼写错误** — 新增 `{emot\w*_\s*[^\s}]+\}` 正则，过滤 AI 拼错前缀的伪标签（如 `{emusement_happy}`）

**Bug 修复**

- **麦克风错误提示** — 独立 WebUI 不再误显 Dashboard 专属提示，按 `IS_DASHBOARD()` 区分
- **历史面板滚动** — 先 `active` 再 `scrollTop`，修复 `display:none` 时无法计算 `scrollHeight`
- **录音编码修复** — Float32→Int16 转换补上 `×32767` 缩放，修复 STT 判为静音

**句子级并行 TTS — 语音延迟大幅降低**

- `_do_bg_tts()` 和 `_send_synthesize_tts()` 改为句子级并行合成：按中英文句号切分文本 → 每句独立调用 TTS → `asyncio.gather` 并行 → ffmpeg 拼接为单文件。多句回复 TTS 时间从 2-5s 降至 ~0.7s（减少 ~70%），单句回复无额外开销
- 新增 `_split_sentences()` — 按中文 `。！？…~` 和英文 `.?!` 切割，保留标点
- 新增 `_build_sentence_tagged_texts()` — 将全文级 emotion 位置重新分配到每句话，无标签句子 fallback `[neutral]`
- 新增 `_parallel_tts()` — gather 并行调用 TTS provider，某句失败时跳过其余继续，全部失败时返回 None
- 新增 `_concat_audio()` — ffmpeg concat demuxer 拼接多个 WAV，成功后清理源文件
- **中性语气 fallback** — `emotions_all` 为空时不再跳过 TTS，改用 `[neutral]` 继续合成，彻底消灭"LLM 不带标签就静音"的 bug

**提示词强化**

- 系统提示词最开头新增 `**重要：每次回复开头必须包含至少一个 {emotion_xxx} 标签**` bold 强调
- 规则 1 从"用口语化中文回复"改为"每条回复至少包含一个标签"
- 自由标签描述从"情绪/语气/动作/状态"改为"声学特征（语气/语调/语速/音色），不得描述动作"
- 新增错误示例禁止 `{emotion_歪头}` 等动作标签和零标签裸回

## v0.7.7

**WebUI 交互重构**

- **设置/收藏页改为 iframe 覆盖层** — 独立 WebUI 不再跳转到独立 HTML 页面，而是在主页面上以 iframe 覆盖层打开。页面永不卸载，消息流不中断，AI 回复正常出现。bfcache 恢复时自动刷新对话框文本
- **跨页面音频持久化** — 设置页选择 BGM 后关闭设置，音乐继续播放不被打断；收藏页语音播到一半切回聊天页不中断。通过 `postMessage` 通信实现
- **BGM 交互优化** — 上传 BGM 后自动选中并开始循环播放；当前 BGM 项增加暂停/播放按钮，替换原来的本地预览按钮
- **Dashboard BGM 支持** — 新增 `/bgm/data` 端点（base64 返回），Dashboard 模式通过 bridge SDK 认证通道加载 BGM，绕过沙箱 iframe 的 cookie 隔离问题。通过 8s 轮询 + `bgm_playing` 服务端状态实现暂停/播放

**语音播放互斥**

- 新增 `_stopVoice()` 统一入口 — TTS、历史回放、收藏播放三者互斥，同时只允许一个音频源出声。历史/收藏页同步「播放即停前序」逻辑

**Bug 修复**

- **音频 404** — `GalgameWebHandler.audio_dir`/`.bgm_dir` 未对齐 `AUDIO_DIR`/`BGM_DIR`，导致收藏页语音和 BGM 无法加载
- **快速点击幽灵消息** — 覆盖层关闭按钮被计入快速点击检测，触发空发送产生 `"(语音消息)"` + AI 空回复。现所有面板/覆盖层内点击均已排除
- **收藏页孤儿条目** — 加载收藏列表时自动清理音频文件已不存在但收藏条目仍残留的情况
- **LLM 响应超时** — pipeline 等待从 120s 提高到 300s
- **temp 目录 CWD 依赖** — 录音临时文件改用 `get_astrbot_data_path()`

**配置变更**

- 删除 `history_limit` 配置项 — 历史记录显示条数改为跟随 AstrBot 平台设置（`provider_settings.max_context_length` ×2）
- 新增 `rapid_click_enabled`（bool）— 可在 AstrBot 仪表盘插件配置页关闭「快速点击 AI 主动关心」功能

## v0.7.6

- **对话框字号可调** — 插件配置页新增 `font_size` 配置项，默认 17px，建议 14~24。独立 WebUI 和 Dashboard 内嵌页均生效

## v0.7.1

**Dashboard 内嵌页修复**

- 修复设置页无法删除文件：移除 `confirm()` 弹窗（Dashboard sandbox 无 modals 权限），单删、批量删、BGM 删均已修复
- 修复上传后图片显示黑色占位符：`preloadAssets()` 改为先获取全量文件列表再一次性 `assets/batch` 预加载进 `_assetCache`，文件网格全部使用 base64 数据 URL

## v0.7.5

- **用户语音消息历史回放** — 用户通过麦克风发送的语音消息在历史记录中显示 "(语音消息)" + ▶ 播放按钮，可回放自己的录音。音频自动存入 `AUDIO_DIR`，支持收藏
- **LLM 超时自动恢复** — LLM 响应较慢导致浏览器端 HTTP 超时时，不再显示「发送失败」，改为从服务端读取已写入的历史记录自动恢复显示
- 删除 STT 转录文本提取代码（`_inject_galgame_rules`），用户语音消息在历史中以音频文件形式呈现

## v0.7.4

- 修复 Dashboard 内嵌页麦克风错误提示误导用户 → 改为指引用户使用独立 WebUI
- 移除 `_migrate_old_assets()` 函数及调用（不再自动复制默认示例图）
- README 已知限制补充：内嵌页无麦克风权限

## v0.7.0

**配对表情标签系统强化**

- 提示词升级为配对格式：要求 AI 每次情绪变化输出两个标签 `{emotion_自由}{emotion_立绘}`，自由标签（TTS 语气）+ 必选立绘标签（立绘切换）。同名时只写一个，确保立绘切换和语音语气同步
- `_build_tagged_text` 重构为按位置分组处理，同位置多标签输出堆叠格式 `[tag1][tag2]text`，自由标签不再被后一个覆盖丢失
- `_conf_schema.json` 默认提示词与 `DEFAULT_GALGAME_PROMPT` 完全同步，新增 emoji 输出禁止规则

**Dashboard 内嵌页面**

- 新增三个 Dashboard 内嵌页面：`pages/galgame/`（对话）、`pages/settings/`（设置/立绘/BGM/音量）、`pages/voice-favorites/`（语音收藏），通过插件卡片入口顶部 tab 切换
- 所有内嵌页面通过 bridge SDK (`window.AstrBotPluginPage`) 自动认证，sandboxed iframe 兼容（`localStorage` 沙箱回退、`async/await` → `.then()` 降级、bridge SDK 轮询启动）
- 对话页和独立 WebUI 的 `app.js` 合并为同一文件，通过 `IS_DASHBOARD()` 运行时自适应双环境

**独立 WebUI 密码保护**

- 新增 `web_enabled` 和 `web_password` 配置项：可关闭独立 HTTP 服务器，或在开启时设置访问密码（HMAC 签名 cookie，24h 有效，无密码时完全跳过）
- 登录页风格统一（紫色渐变 + 毛玻璃，匹配 galgame 主页面）

**收藏功能改进**

- 对话框 ❤ 按钮改为 toggle：点击收藏（实心红），再次点击取消（空心），立即切换无需刷新
- 历史面板每条语音的 ❤ 按钮同步 toggle，初始状态自动跟随已收藏列表
- 收藏数据持久化到 `favorites.json`，独立 WebUI 和 Dashboard 内嵌共享同一份数据

**会话管理增强**

- 会话切换面板：顶部列表图标进入，浏览/切换/删除历史会话，API 原地切换不跳转页面（替代原来的 URL 重定向方式）
- 会话指令（`/new`/`/del`/`/reset`）、删除按钮、空壳清理等基础设施已在 v0.6.0 引入，v0.6.1 主要完善了 Dashboard 兼容性和前端体验

**音频管理**

- 音量全局生效：历史/收藏页面播放尊重音量滑块，页面可见性变化时自动刷新音量
- 音频格式 wav/mp3（`audio_format` 配置）和孤儿清理已在 v0.6.0 引入，v0.6.1 完善了连动删除和收藏保护

**代码重构**

- `main.py` 拆为 `api/` 子模块（assets/audio/bgm/config/favorites/prefs/session），主文件 1050→220 行
- `_api_send` 拆为 9 个子步骤方法
- 全项目通过 ruff format + ruff check（31 issues 全部修复）

**Bug 修复**

- 修复 TTS 不触发：AI 只用自由标签（无立绘标签）时 `emotions` 为空导致 guard 跳过
- 修复系统指令回复触发 TTS：`/reset`/`/new` 等指令回复不再合成语音
- `_build_tagged_text` 空情绪列表时返回 `[neutral]text` 作为缺省
- 修复 Markdown 格式被 TTS 朗读：提示词禁止 `**粗体**`、`*斜体*`、`` `代码` ``、`#标题` 等
- 修复 `tts_enabled` 配置类型 `boolean` → `bool`
- 修复浏览器录音 WAV 编码缺陷：Float32 样本缺少 ×32767 缩放导致音量极低
- 修复 `{emotion_ xxx}` 带空格的标签无法匹配，正则宽松化
- 修复模型空回复时前端对话框空白，回退显示省略号
- 修复 meme_manager 产生的 `[IMAGE]` 引用显示在对话框
- 修复 `_build_tts_segments` 情绪错位（`{emotion_xxx}` 在文本开头时后续分段全用错情绪）
- 修复 sandboxed iframe 中 `localStorage` 被禁导致页面无法初始化
- 修复「开始全新对话」不生效：服务端 auto-resume 覆盖 `startNewSession`，新增 `force_new` 参数跳过自动恢复
- 修复新建会话后对话框残留旧对话文本：`restoreLastMessage` 无历史时清空显示
- 修复 Dashboard 内嵌页无法删除会话：sandbox 无 `confirm()` 权限，改为直接执行删除
- 修复 ffmpeg 转码阻塞事件循环：`_convert_audio` 改用 `asyncio.to_thread` 在后台线程执行

**审核规范化**

- 数据路径全部改用 `StarTools.get_data_dir(PLUGIN_NAME)`（替代硬编码的 `pathlib.Path("data/plugin_data")/...`），符合官方插件上架规范，确保 Docker 部署数据不丢失

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
