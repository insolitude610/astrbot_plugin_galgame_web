# AI Galgame 虚拟伙伴

[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-blue)](https://github.com/AstrBotDevs/AstrBot)

一个 AstrBot 插件，通过独立本地端口提供 Galgame 风格的 AI 虚拟伙伴 WebUI。支持 3D VRM 模型渲染、双图交叉渐变表情切换、TTS 语音朗读、快速点击检测等交互特性。

## 功能亮点

- **3D VRM 模型支持** —— 上传 `.vrm` 模型（VRoid Studio 免费导出），Three.js 渲染真实 3D 角色
- **AI 驱动表情切换** —— VRM 内置 blend shapes，支持 neutral/happy/sad/angry/surprised/blush/thinking
- **自动眨眼 + 视线跟踪** —— VRM 原生 `autoBlink` + `lookAt`，眼睛跟随鼠标
- **情绪实时切换** —— AI 回复中标记 `{emotion_happy}` 等标签，立绘表情实时切换
- **复用 AstrBot 人格系统** —— 直接选择已配置的 Persona，无需重复设定角色性格
- **TTS 语音朗读** —— 接入 AstrBot 内置或第三方 TTS Provider（Edge/OpenAI/Azure/DashScope 等），受限于同步 API 架构暂不可用
- **打字机效果** —— 回复文字逐字显示
- **快速点击检测** —— 用户频繁点击鼠标/键盘时 AI 主动关心
- **双渲染模式** —— `single` 双图交叉渐变 或 `vrm` 3D 模型渲染
- **对话历史面板** —— 内建聊天记录查看，气泡式展示，背景色自适应
- **语音输入** —— 浏览器麦克风录音，经 AstrBot STT 管道自动转文字
- **AstrBot 指令全兼容** —— `/reset /new` 等所有已注册指令通过管道分发
- **立绘位置可调** —— `sprite_bottom` / `sprite_left` / `sprite_scale` 配置项
- **批量删除** —— 立绘管理页多选文件一键删除
- **会话持久化** —— 对话历史自动存盘，重启后保留；localStorage 记录 session_id
- **立绘管理页面** —— 浏览器内上传 / 预览 / 删除素材，自动匹配文件
- **同步请求/响应** —— `send` API 返回完整回复（文本 + 情绪），前端本地播打字机动画

## 快速开始

> **推荐**：`single` 模式最稳定——每情绪一张全身 PNG 即可。`vrm` 模式需要 3D 模型文件（从 VRoid Studio 免费导出，或从 VRoid Hub 下载现成模型）。

### 安装

1. 在 AstrBot WebUI 中打开**插件市场**
2. 搜索 `astrbot_plugin_galgame_web` 并安装
3. 启用插件

### 配置

在插件详情页配置以下内容：

| 配置项 | 说明 | 推荐 |
|--------|------|------|
| 角色显示名 | 对话框上方显示的名称 | 你的角色名 |
| 角色人格 | 选择已在 AstrBot 配置好的 Persona | AstrBot 预设或自建 |
| LLM Provider | 驱动对话的 AI 模型 | deepseek / gpt-4o |
| TTS Provider | 语音合成（暂不可用） | 等待后续修复 |
| 立绘渲染模式 | `single` 双图交叉渐变 或 `vrm` 3D模型 | single 最稳定 |
| VRM 模型文件 | `.vrm` 格式 3D 模型文件路径 | 留空自动匹配 assets/ 目录下 .vrm 文件 |
| 立绘缩放比例 | 整体缩放倍数 | 默认 1.0，建议 0.5 ~ 2.0 |
| 立绘底部位置 | vh 距离底部，越小越靠下 | 默认 28，建议 5 ~ 45 |
| 立绘水平位置 | 水平锚点 % 位置 | 默认 50（居中） |
| 独立 WebUI 端口 | 插件启动的独立 HTTP 服务器端口 | 默认 6186，设为 0 关闭 |
| 自定义情绪 | JSON 格式添加额外情绪标签 | 例：`{"dokidoki": ""}` |
| 会话保留天数 | 超过该天数未活跃的会话自动清理 | 默认 7 天，0 = 永不清理 |

**关于表情/图层/背景配置项**：这些字段均标注「留空 = 自动」，按[文件命名约定](#文件命名约定)将 PNG 放入 `assets/` 目录或通过[立绘管理页面](#立绘管理页面)上传即可，无需手动逐个填写。

### 使用

**打开界面：**

插件启动后会自动在本机启动一个 HTTP 服务器（默认端口 6186），浏览器直接访问即可：

```
http://localhost:6186
```

也可以在任意接入 AstrBot 的消息平台发送 `/galgame`，Bot 会回复访问地址。

打开后在输入框输入文字即可对话。

> **注意**：WebUI 通过该独立端口访问，不在 AstrBot Dashboard 内嵌显示。端口可在插件配置中修改。

---

## 渲染模式与立绘说明

插件支持两种立绘渲染模式，通过配置项 `sprite_mode` 切换。两种模式对上传的图片**有完全不同的要求**。

### Single 模式（`sprite_mode: single`）

**原理**：一张完整的半身角色 PNG 就是一个表情状态。AI 切换情绪时，整张图直接替换。

**需要上传的图片**：每种情绪对应**一整张完整半身立绘**（身体 + 头 + 衣服 + 头发全在一张图里）。

| 配置项 | 应上传的文件 | 说明 |
|--------|------------|------|
| `neutral` | 完整半身立绘（普通表情） | **必须**，其他情绪缺省时回落此图 |
| `happy` | 完整半身立绘（开心表情） | AI 标记 `{emotion_happy}` 时显示 |
| `sad` | 完整半身立绘（悲伤表情） | 同上 |
| `angry` | 完整半身立绘（生气表情） | |
| `surprised` | 完整半身立绘（惊讶表情） | |
| `blush` | 完整半身立绘（害羞表情） | |
| `thinking` | 完整半身立绘（思考表情） | |

**视觉效果**：角色整体缓慢上下浮动（CSS 呼吸动画），表情切换时 fade 过渡。

---

### VRM 模式（`sprite_mode: vrm`）

**原理**：上传一个 `.vrm` 3D 模型文件（从 VRoid Studio 免费导出），Three.js + three-vrm 在浏览器中实时渲染 3D 动漫角色。VRM 原生支持表情 blend shapes、自动眨眼、眼动追踪、骨骼呼吸等。

**核心特性**：

| 动画效果 | 实现方式 |
|---------|---------|
| 自动眨眼 | VRM 原生 `autoBlink`，随机 2-5 秒眨眼一次 |
| 视线跟踪 | `VRM.lookAt.target` 绑定鼠标位置，眼睛跟随光标 |
| 表情切换 | VRM blend shapes：`expressionManager.setValue("happy", 1.0)` |
| 呼吸起伏 | Three.js 骨骼默认微动 + DirectionalLight 立体光影 |
| 3D 旋转 | 可拖拽改变视角，或固定正面朝向 |

**需要上传的素材**：

| 素材 | 格式 | 来源 | 说明 |
|------|-----|------|------|
| VRM 模型 | `.vrm` | VRoid Studio（免费） | 一个文件包含模型、骨骼、表情、纹理全部 |
| 可选背景 | PNG/JPG | 任意 | 与 single 模式共用 |

**表情映射**：

| AI 标签 | VRM Blend Shape |
|---------|----------------|
| `neutral` | neutral |
| `happy` | happy |
| `sad` | sad |
| `angry` | angry |
| `surprised` | surprised |
| `blush` | relaxed |
| `thinking` | neutral |

**获取 VRM 模型**：

1. 下载 [VRoid Studio](https://vroid.com/en/studio)（免费）
2. 捏脸 10 分钟
3. 导出 `.vrm` 文件
4. 上传到插件 assets/ 目录（立绘管理页面 → VRM 区）
5. 设置 `sprite_mode` 为 `vrm`

或从 [VRoid Hub](https://hub.vroid.com/) 直接下载数十万个免费模型。

---

### 两种模式对照速查

| | Single 模式 | VRM 模式 |
|----|-----------|------------|
| 素材 | 每情绪 1 张 PNG | 1 个 .vrm 文件 |
| 渲染 | CSS + Canvas 2D | Three.js WebGL |
| 表情切换 | 双 img 交叉渐变 0.6s | VRM blend shape 切换 |
| 眨眼 | 无 | 原生 autoBlink |
| 视线跟踪 | 无 | 眼睛跟随鼠标 |
| 呼吸 | CSS translateY | 骨骼微动 |
| 制作成本 | AI 生图 | VRoid Studio 免费捏脸 |
| 素材来源 | Stable Diffusion 等 | VRoid Hub（数十万免费模型） |

---

## 情绪与表情系统

### 工作原理

插件后端会在 system prompt 中要求 AI 在回复中插入 `{emotion_xxx}` 标签。后端解析标签后，将回复文本和情绪序列一并返回给前端，前端根据情绪名在打字机动画中实时切换立绘表情。

### 默认情绪列表

| 标签 | 含义 | 触发场景示例 |
|------|------|------------|
| `neutral` | 普通 | 日常对话中 |
| `happy` | 开心 | 用户夸奖、好消息 |
| `sad` | 悲伤 | 用户诉苦、坏消息 |
| `angry` | 生气 | 用户不礼貌、矛盾 |
| `surprised` | 惊讶 | 突然的信息、意外 |
| `blush` | 害羞 | 用户调侃、暧昧 |
| `thinking` | 思考 | 被问到难题、认真想 |

### 自定义情绪

插件默认提供 7 种情绪（neutral / happy / sad / angry / surprised / blush / thinking）。如需额外情绪，在插件配置页的 **「自定义情绪」** 字段中写入 JSON 对象：

```json
{"dokidoki": "dokidoki.png", "cry": "", "smirk": "smirk.png"}
```

- **key**：情绪标签名，AI 会用 `{emotion_key}` 标记
- **value**：`assets/` 下的文件名（留空则自动匹配 `key.png`）

后端会自动将自定义情绪与默认 7 种合并，system prompt 会列出全部情绪标签。注意：新增情绪后需上传对应的表情图。

---

## 立绘管理页面

在 Galgame 主页面右上角点击齿轮 ⚙ 图标进入。支持：

- **拖拽上传** — PNG 图片拖入页面即可上传到 `assets/` 目录
- **按模式分区** — 页面按当前渲染模式显示需要的文件清单，每个槽位独立上传
- **自动重命名** — 从槽位上传的文件自动改名为标准文件名（如 `happy.png`），解决命名不匹配问题
- **匹配状态表** — 一目了然哪些表情/图层/背景已配齐、哪些还缺失
- **文件网格** — 浏览/预览/删除所有已上传文件

### 文件命名约定

上传到 `assets/` 后，按文件名**子串匹配**自动关联到对应配置项：

| 配置项 | 推荐文件名（Single） | 推荐文件名（Layered） | 匹配关键字 |
|--------|-------------------|---------------------|----------|
| 表情 neutral | `single_neutral.png` | `expr_neutral.png` | `neutral` |
| 表情 happy | `single_happy.png` | `expr_happy.png` | `happy` |
| 表情 sad | `single_sad.png` | `expr_sad.png` | `sad` |
| 表情 angry | `single_angry.png` | `expr_angry.png` | `angry` |
| 表情 surprised | `single_surprised.png` | `expr_surprised.png` | `surprised` |
| 表情 blush | `single_blush.png` | `expr_blush.png` | `blush` |
| 表情 thinking | `single_thinking.png` | `expr_thinking.png` | `thinking` |
| 背景 background | `bg_background.png` | `bg_background.png` | `background` 或 `bg` |
| VRM 模型 | — | `model.vrm` | `.vrm` 文件 |

---

## 会话持久化说明

每次与 AI 对话后，对话历史保存到 `data/plugin_data/astrbot_plugin_galgame_web/sessions/`。浏览器 localStorage 记录 session_id，下次打开页面自动恢复。

### 会导致会话消失的情况

| 情况 | 是否丢失 | 原因 |
|------|:--:|------|
| 重载/重启 AstrBot | 否 | 从磁盘恢复 |
| 插件升级/重装 | 否 | 会话文件不受影响 |
| 关闭浏览器再打开 | 否 | localStorage 记录 session_id |
| 超过保留天数的旧会话 | **是** | GC 自动清理（默认 7 天） |
| 手动删除 `sessions/` 目录 | **是** | 物理删除 |
| 更换浏览器 | **是** | localStorage 不共享 |
| 无痕/隐私模式 | **是** | localStorage 不持久化 |
| 清除浏览器缓存 | **是** | localStorage 被清 |
| 换个电脑/设备 | **是** | 无跨设备同步 |

> 将会话保留天数设为 `0` 则永不清理。

---

## 立绘生成指南

使用 AI 图片生成（gpt-image-2、Stable Diffusion 等）。

**主体立绘 prompt：**

```
2D anime-style character illustration, half-body portrait,
front-facing, standing pose with relaxed posture.
[你的角色描述]
Clean lineart, soft anime cel-shading,
Solid light-gray background. Aspect ratio 3:4.
No dialog box, no text, no UI elements.
```

**表情差分 prompt：**

```
Same character. Identical appearance: [外观要点].
Facial expression: [表情描述].
Same light-gray background, same 3:4 composition.
```

**闭眼变体 prompt：**

```
Same character. Identical appearance and pose.
Eyes gently closed, peaceful/blinking expression.
Same background, same composition.
```

---

## API 响应格式

`POST /api/plug/astrbot_plugin_galgame_web/send` 返回：

```json
{
  "reply": "AI 回复文本（已去除情绪标签）",
  "emotion": "happy"
}
```

前端收到后执行打字机动画显示 `reply`，并根据 `emotion` 切换立绘表情。

---

## 技术架构

```
浏览器 (http://localhost:6186)
  ├─ 静态文件 → 插件内置 HTTP Server (ThreadingHTTPServer)
  └─ /api/* → 代理至 AstrBot Core (Quart :6185) → fetch 同步请求
```

- 前端: 原生 HTML/CSS/JS，Canvas 2D 渲染，无框架依赖
- 后端: Python `http.server` + AstrBot Star API
- 通信: `fetch()` 同步请求/响应，通过本地代理与 AstrBot Core 交互，JWT Bearer 认证
- 管道: 所有对话经 webchat 管道分发，接入记忆/感知/安全等全插件栈

## 变更记录

### v0.5.0

- **VRM 3D 模式** — `sprite_mode` 新增 `vrm` 选项，使用 Three.js + three-vrm 渲染 3D 动漫角色
- **原生动画** — VRM 自动眨眼、视线跟踪鼠标、表情 blend shape 切换、骨骼呼吸
- **零成本建模** — 支持 VRoid Studio（免费）导出的 .vrm 模型，VRoid Hub 数十万免费模型
- 删除 Canvas 分层立绘引擎（hair wave / blink image swap / CSS breathing）
- 从配置中移除 `expressions_blink` 和旧 `layers` 结构
- 新增 `vrm_model` 配置项 + `_api_config` 返回 VRM 文件路径
- `_resolved_assets` 新增 .vrm 文件自动检测
- Single 模式完全不变

### v0.4.0

- **Layered 模式重写** —— 废弃多层 PNG 叠加，改为 Canvas 单图逐行正弦形变渲染
- **眨眼系统** —— 每情绪可选 `_blink` 闭眼变体图，真正换图眨眼（替换旧的 scaleY 压扁方案）
- **呼吸动画升级** —— 从 JS 多频正弦波改为纯 CSS `scaleY` + `scaleX` 挤压拉伸（`transform-origin: bottom center`）
- **表情切换渐变** —— Canvas opacity fade out → 换源 → fade in（300ms 过渡）
- **素材简化** —— 不再需要拆分 body/head/hair/mouth 等图层，一张全身立绘即可
- 删除 `LAYER_KEYS`、口型同步、多层动画引擎（净减 81 行代码）
- 后端新增 `expressions_blink` 自动检测与 API 返回
- Single 模式完全不变

### v0.3.0

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

### v0.2.4

- **立绘管理页按模式分区** —— Single / Layered 分区独立展示所需文件清单，当前模式高亮
- **槽位上传自动重命名** —— 从表情/图层槽位上传的文件自动存为标准名（如 `happy.png`），无需手动改名
- **支持自定义情绪** —— 新增 `custom_emotions` 配置字段（JSON），可自由添加额外情绪标签
- 全面重写 README：详述两种模式差异、文件需求、表情系统、命名约定

### v0.2.3

- 立绘管理页面：拖拽上传 / 预览 / 删除 PNG，自动匹配
- 配置页提示优化：表情/分层标注「留空=自动」
- 新增 upload / delete / batch API
- 安全加固：10MB 大小限制、路径遍历防护

### v0.2.2

- Galgame 对话接入 AstrBot 消息系统，Dashboard `#/conversation` 可查看/导出

### v0.2.1

- 立绘路径自动检测：按命名约定即可零配置使用

### v0.2.0

- 前端全面改造为 Galgame 沉浸式 UI
- 角色人格改用 AstrBot 内置 Persona 系统
- 会话持久化 + 可配置保留天数
- 背景图配置
- `/galgame` 指令

### v0.1.0

- 首次发布

## 许可证

MIT

---

**相关项目：**
- [AstrBot](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)
