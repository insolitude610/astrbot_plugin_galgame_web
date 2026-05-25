# 变更记录

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
