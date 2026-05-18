# AI Galgame 虚拟伙伴

[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-blue)](https://github.com/AstrBotDevs/AstrBot)

一个 AstrBot 插件，在浏览器中呈现 Galgame 风格的 AI 虚拟伙伴界面。支持多层 PNG 伪 Live2D 独立动画、AI 驱动情绪表情切换、TTS 语音朗读、快速点击检测等交互特性。

## 功能亮点

- **多层 PNG 伪 Live2D** —— 身体/头发/脸部/嘴部各自独立动画，不依赖 Live2D SDK
- **情绪实时切换** —— AI 回复中标记 `[emotion:happy]` 等标签，立绘表情自动淡入淡出
- **复用 AstrBot 人格系统** —— 直接选择已配置的 Persona，无需重复设定角色性格
- **TTS 语音朗读** —— 接入 AstrBot 内置或第三方 TTS Provider（Edge/OpenAI/Azure/DashScope 等）
- **打字机效果** —— 回复文字逐字显示
- **嘴型同步** —— 播放语音时嘴部自动开合
- **快速点击检测** —— 用户频繁点击鼠标/键盘时 AI 主动关心
- **双层渲染模式** —— 支持完整分层 PNG（layered）或单张立绘 + 表情差分（single）
- **纯 CSS 动画** —— 呼吸、头发摆动、球体漂浮、对话框滑入，零依赖
- **SSE 实时通信** —— 文本逐段推送、情绪即时切换、音频流式播放
- **会话持久化** —— 对话历史自动存盘，重启/重载后保留；localStorage 记录 session_id，关掉页面再打开可继续对话
- **立绘管理页面** —— 浏览器内拖拽上传 / 预览 / 删除 PNG，自动匹配情绪/图层

## 快速开始

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
| TTS Provider | 语音合成 | Edge TTS（免费） |
| 立绘渲染模式 | `single` 单图 或 `layered` 多层 | layered 效果更好 |
| 自定义情绪 | JSON 格式添加额外情绪标签 | 例：`{"dokidoki": ""}` |
| 会话保留天数 | 超过该天数未活跃的会话自动清理 | 默认 7 天，0 = 永不清理 |

**关于表情/图层/背景配置项**：这些字段均标注「留空 = 自动」，按[文件命名约定](#文件命名约定)将 PNG 放入 `assets/` 目录或通过[立绘管理页面](#立绘管理页面)上传即可，无需手动逐个填写。

### 使用

**打开界面：**

- **方式一**：AstrBot Dashboard → 插件 → AI Galgame 虚拟伙伴 → 点击「Galgame」页面
- **方式二**：浏览器访问 Dashboard 地址后追加 `/api/plugin/page/content/astrbot_plugin_galgame_web/galgame/index.html`
- **方式三**：在任意接入 AstrBot 的消息平台发送 `/galgame`，Bot 会回复打开方式

打开后在输入框输入文字即可对话。

---

## 渲染模式与立绘说明

插件支持两种立绘渲染模式，通过配置项 `sprite_mode` 切换。两种模式对上传的图片**有完全不同的要求**。

### Single 模式（`sprite_mode: single`）

**原理**：一张完整的半身角色 PNG 就是一个表情状态。AI 切换情绪时，整张图直接替换。

**需要上传的图片**：每种情绪对应**一整张完整半身立绘**（身体 + 头 + 衣服 + 头发全在一张图里）。

| 配置项 | 应上传的文件 | 说明 |
|--------|------------|------|
| `neutral` | 完整半身立绘（普通表情） | **必须**，其他情绪缺省时回落此图 |
| `happy` | 完整半身立绘（开心表情） | AI 标记 `[emotion:happy]` 时显示 |
| `sad` | 完整半身立绘（悲伤表情） | 同上 |
| `angry` | 完整半身立绘（生气表情） | |
| `surprised` | 完整半身立绘（惊讶表情） | |
| `blush` | 完整半身立绘（害羞表情） | |
| `thinking` | 完整半身立绘（思考表情） | |

**不需要**：任何图层文件（`body`、`head`、`hair_*`、`mouth_*` 等），这些仅 layered 模式使用。

**视觉效果**：角色整体缓慢上下浮动（呼吸动画），表情切换时 fade 过渡。

---

### Layered 模式（`sprite_mode: layered`）

**原理**：角色被拆成多个透明 PNG 图层叠在一起，每一层有独立的 CSS 动画。AI 切换情绪时**只替换脸部那一层**，身体/头发/嘴部不动。

**需要上传的图片分为两类**：

#### A. 图层文件（固定不动，与情绪无关）

| 图层 | 应上传的文件 | CSS 动画 | 说明 |
|------|------------|----------|------|
| `body` | **只有脖颈以下身体**的透明 PNG | 上下呼吸浮动（4s） | 不能包含头部，因为头上要叠 face 层 |
| `head` | **只有脸部五官**的透明 PNG（默认表情） | 轻微倾斜（7s） | 这是初始脸。表情切换时此层被替换 |
| `hair_back` | 只有后部头发的透明 PNG | 慢速左右摆（5s） | 可选 |
| `hair_front` | 只有前刘海/侧发的透明 PNG | 相位偏移摆动（6s） | 可选 |
| `mouth_open` | 只有嘴部的透明 PNG（张嘴） | TTS 播放时快速交替 | 需要配套 `mouth_closed` 才生效 |
| `mouth_closed` | 只有嘴部的透明 PNG（闭嘴） | TTS 结束/未播放时显示 | |
| `orb` | 头顶漂浮物的透明 PNG | 随机漂浮（3s） | 可选 |

#### B. 表情文件（每种情绪一张，运行时替换 `head` 层）

| 配置项 | 应上传的文件 | 说明 |
|--------|------------|------|
| `neutral` | **仅脸部区域**的透明 PNG（普通表情） | 必须，回落图 |
| `happy` | 仅脸部区域的透明 PNG（开心） | AI 标记 `[emotion:happy]` 时替换 head 层 |
| `sad` | 仅脸部区域的透明 PNG（悲伤） | |
| `angry` | 仅脸部区域的透明 PNG（生气） | |
| `surprised` | 仅脸部区域的透明 PNG（惊讶） | |
| `blush` | 仅脸部区域的透明 PNG（害羞） | |
| `thinking` | 仅脸部区域的透明 PNG（思考） | |

> **关键区别**：Layered 模式下表情文件**只应该包含脸部**，而不是全身。因为 body 层已有身体，head 层只用换脸。

**视觉效果**：身体呼吸 + 头发各自飘动 + 表情切换只换脸 + TTS 说话时嘴部自动张合 + 球体漂浮。这是伪 Live2D 效果。

---

### 两种模式对照速查

| | Single 模式 | Layered 模式 |
|----|-----------|------------|
| 表情图内容 | 完整半身立绘 | **仅脸部区域** |
| 需要图层文件 | 不需要 | body / head / mouth 等 |
| 表情切换范围 | 全身替换 | 仅替换脸部 |
| 头发飘动 | 无 | 有（需上传 hair_* 层） |
| 嘴型同步 | 无 | 有（需上传 mouth_*） |
| 实现难度 | 低 | 中（需拆层） |

---

## 情绪与表情系统

### 工作原理

插件后端会在 system prompt 中要求 AI 在回复末尾附上 `[emotion:xxx]` 标签。后端解析标签后通过 SSE 推送给前端，前端根据情绪名查 `expressions` 映射表，将立绘切换为对应表情图。

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

- **key**：情绪标签名，AI 会用 `[emotion:key]` 标记
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

| 配置项 | 推荐文件名 | 主要匹配关键字 |
|--------|-----------|--------------|
| 表情 neutral | `neutral.png` | `neutral` |
| 表情 happy | `happy.png` | `happy` |
| 表情 sad | `sad.png` | `sad` |
| 表情 angry | `angry.png` | `angry` |
| 表情 surprised | `surprised.png` | `surprised` |
| 表情 blush | `blush.png` | `blush` |
| 表情 thinking | `thinking.png` | `thinking` |
| 图层 body | `body.png` | `body` |
| 图层 head | `head.png` | `head` |
| 图层 hair_back | `hair_back.png` | `hair_back` |
| 图层 hair_front | `hair_front.png` | `hair_front` |
| 图层 mouth_open | `mouth_open.png` | `mouth_open` |
| 图层 mouth_closed | `mouth_closed.png` | `mouth_closed` |
| 图层 orb | `orb.png` | `orb` |
| 背景 background | `background.png` 或 `bg.png` | `background` 或 `bg` |

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

**获取分层图的方法**：AI 只能出完整图，需用 GIMP/Photoshop 拆分：

1. 从主体立绘中去背景
2. 从脖子位置切开 → 上半为 `head.png`、下半为 `body.png`
3. 抠出刘海和侧发 → `hair_front.png`
4. 抠出后部头发 → `hair_back.png`
5. 从表情脸图中裁出嘴部 → `mouth_open.png` / `mouth_closed.png`

> 可以用 [sprite-gen-AIHubmix](https://github.com/insolitude610/sprite-gen-AIHubmix) 自动化生成 + 拆层流程。

---

## SSE 事件协议

| 字段 | 类型 | 说明 |
|------|------|------|
| `type: "emotion"` | 切换情绪 | `value` 为情绪标签 |
| `type: "text"` | 文本流 | `value` 为逐段推送的回复文字 |
| `type: "audio"` | 语音 | `value` 为 base64 编码的 WAV 音频 |
| `type: "end"` | 回复完毕 | 无额外字段 |
| `type: "error"` | 错误 | `message` 为错误描述 |

---

## 技术架构

```
浏览器 (Galgame UI)
  ↕ Bridge API + SSE
AstrBot Dashboard (Quart)
  ↕ register_web_api
插件后端 main.py
  ↕ context.llm_generate / context.get_provider_by_id
AstrBot Core
  └─ LLM + TTS + Persona + 会话管理
```

---

## 变更记录

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
- [sprite-gen-AIHubmix](https://github.com/insolitude610/sprite-gen-AIHubmix) — 立绘生成 + 拆层自动化工具
