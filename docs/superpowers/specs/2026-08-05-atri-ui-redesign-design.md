# ATRI 蓝白冷调 UI 重设计

日期：2026-08-05
状态：设计阶段（用户已确认方向：ATRI 蓝白冷调、浮动卡片微调、面板深蓝灰、标题衬线+正文黑体+可自定义字体、收藏页取消收藏加确认）
目标版本：v0.8.1

## 1. 背景

用户反馈当前 WebUI "紫紫的一看就是 AI 干的"。期望向前翼社《ATRI -My Dear Moments-》的界面气质靠拢：浅色半透明对话框、克制的小圆角与细边框、无浓毛玻璃/霓虹/发光，管理面板采用游戏系统菜单式的深色中性配色。

## 2. 设计原则

- **布局零改动**：仅换皮肤（style.css 配色 + 字体 + 少量新增 UI），不动 HTML 结构（浮动卡片微调）
- **双端一致**：Dashboard 内嵌页 + 独立 WebUI 全量同步（孪生文件 MD5 一致；settings/favorites 双实现逐项同步）
- **克制**：细边框、小圆角（8px）、细阴影、无渐变紫、无发光、少装饰

## 3. 色板（ATRI 蓝白冷调）

| 令牌 | 值 | 用途 |
|------|-----|------|
| `--dialog-bg` | `rgba(248,250,255,.84)` | 主对话框冷白半透明 |
| `--dialog-text` | `#1e2a3a` | 对话框正文（深蓝灰） |
| `--dialog-border` | `rgba(150,180,215,.35)` | 对话框细边框 |
| `--dialog-shadow` | `0 4px 24px rgba(30,50,80,.14)` | 细阴影（非浓阴影） |
| `--name-tag-bg` | `rgba(208,224,244,.85)` | 角色名标签浅蓝半透明 |
| `--name-tag-text` | `#24405e` | 角色名文字 |
| `--panel-bg` | `rgba(20,30,48,.90)` | 历史/会话/设置/收藏/确认框面板（深蓝灰） |
| `--panel-text` | `#dbe7f5` | 面板浅蓝灰文字 |
| `--panel-border` | `rgba(140,170,210,.28)` | 面板细边框 |
| `--accent` | `#5b8cc4` | 蓝色强调（hover/选中） |
| `--danger` | `#d05663` | 删除/取消收藏（红，保留） |
| `--input-line` | `rgba(150,180,215,.55)` | 输入框底部下划线 |
| toast/确认弹层 | 面板深蓝灰底 + 浅色文字（当前紫色弹层同步换色） | — |

## 4. 字体系统

- **标题/角色名**（默认衬线）：`"Noto Serif SC", "Source Han Serif SC", "Songti SC", "SimSun", Georgia, serif`
- **正文**（默认黑体）：`"PingFang SC", "Noto Sans SC", "Microsoft YaHei", "Segoe UI", sans-serif`
- 通过 CSS 变量注入：`--font-title` / `--font-body`（`document.documentElement.style`）
- 不打包字体文件（系统字体栈 + 回退）

### font_style 偏好（prefs.json 新键）

| 值 | 效果 |
|----|------|
| `"serif"`（默认） | 标题衬线 + 正文黑体 |
| `"sans"` | 全部黑体 |
| `""` | 系统默认（不设置 CSS 变量） |

## 5. 改动清单

### 后端（2 个文件）

| 文件 | 改动 |
|------|------|
| `api/prefs.py` | `_api_prefs_set` 支持 `font_style` 键：枚举校验（`serif`/`sans`/`""`，非枚举返回 400），写入 prefs |
| `api/config.py` | 返回 `"font_style": prefs.get("font_style", "serif")` |

### 主页面（双端孪生：pages/galgame ↔ galgame_web/galgame）

| 文件 | 改动 |
|------|------|
| `style.css` | 全面替换紫色系：对话框/角色名/输入框/按钮/图标/面板/历史/会话/弹层/toast 按色板改色；`:root` 定义 `--font-title`/`--font-body` 默认值并应用到 `.dialog-text`、`#character-name`、面板标题 |
| `app.js` | `applyConfig` 读取 `cfg.font_style` 应用 CSS 变量（默认 `"serif"`）；`_handleComms` 增加 `font-change` 消息处理（设置页改字体后即时生效） |

### 设置页（双实现：pages/settings ↔ galgame_web/galgame/settings.html）

| 文件 | 改动 |
|------|------|
| `pages/settings/style.css` | 紫色系 → 深蓝灰/浅色中性 |
| `pages/settings/index.html` | 新增「字体」设置区：三个选项（默认/全黑体/系统默认）radio |
| `pages/settings/app.js` | 加载/保存 `font_style`（POST prefs + 主页面 postMessage `font-change`）；页面自身也应用字体 |
| `galgame_web/galgame/settings.html` | 同步以上三处（配色/字体区/逻辑） |

### 收藏页（双实现：pages/voice-favorites ↔ galgame_web/galgame/favorites.html）

| 文件 | 改动 |
|------|------|
| `pages/voice-favorites/index.html` | 暖棕 → 冷调配色（深蓝灰容器 + 浅蓝文字）；新增确认弹层 DOM + 样式（showConfirm 组件） |
| `pages/voice-favorites/app.js` | 取消收藏按钮包 `showConfirm("取消收藏这条语音？")`；showConfirm/showToast 组件（弹层此前仅有 toast） |
| `galgame_web/galgame/favorites.html` | 同步配色 + 确认弹层（内联） |

## 6. 行为一致性

- 收藏页取消收藏：**双端均弹确认**（本次从"一键"改为确认——用户新需求）
- 主页面 ❤ toggle：保持一键（快速收藏操作不加确认）
- 字体偏好：双端共享同一 prefs（存服务端），设置页保存后主页面即时生效（postMessage，BroadcastChannel 兜底轮询同 BGM 机制）

## 7. 验证

- `node --check` 全部改动 JS/HTML 内联脚本
- galgame 双端 app.js/style.css/index.html MD5 一致（index.html 结构差异按既有规则处理）
- `python -m pytest tests/ -q` 64 项全绿（后端小改不破坏现有）
- ruff check 通过
- 残留扫描：无原生 confirm/alert
- 手动清单（用户自测）：双端主页面配色/字体、设置页字体切换即时生效、收藏页取消收藏弹确认、面板配色

## 8. 范围外

- 布局调整（保持浮动卡片）
- 立绘/背景/BGM/打字机机制
- 多角色 MVP（另案）
