# 视觉小说冷色调 UI 重设计实施计划

> **For agentic workers:** 设计文档：`docs/superpowers/specs/2026-08-05-visual-novel-ui-redesign-design.md`。实施前需 solution-reviewer-pro 审查，实施后需 quality-reviewer-pro 终审。

**Goal:** 将 WebUI 从紫色系改为 视觉小说冷色调（浅色对话框 + 深蓝灰面板 + 衬线标题），支持设置页自定义字体，收藏页取消收藏加确认弹层。布局零改动，双端全量生效。

**Architecture:** 仅皮肤层替换：style.css 配色 + CSS 变量字体系统 + prefs 新键 `font_style`。孪生文件同步（app.js/style.css），settings/favorites 双实现逐项同步。

**Tech Stack:** 原生 CSS/JS + Python（api/prefs.py、api/config.py 小改）。

**基线:** main @ 9fc612a（v0.8.0），64 测试全绿。

---

### Task 1: 后端 font_style 支持

**Files:** `api/prefs.py`、`api/config.py`

- [ ] 1. `api/prefs.py` `_api_prefs_set` 增加：

```python
if "font_style" in data:
    font_style = data["font_style"]
    if not isinstance(font_style, str) or font_style not in ("serif", "sans", ""):
        return {"error": "invalid font_style"}, 400
    prefs["font_style"] = font_style
```

- [ ] 2. `api/config.py` 返回字典增加：`"font_style": _load_prefs().get("font_style", "serif")`（`_load_prefs` 已 import）
- [ ] 3. 验证：`python -m pytest tests/ -q`（64 项全绿）+ ruff

### Task 2: 主页面双端（style.css 配色 + app.js 字体应用）

**Files:** `pages/galgame/style.css`、`pages/galgame/app.js` → 镜像 `galgame_web/galgame/`

- [ ] 1. `style.css` 配色替换（按 spec 色板）：

| 选择器 | 现值（紫） | 改为 |
|--------|-----------|------|
| `#dialog-box` | 深紫毛玻璃 | `background: rgba(248,250,255,.84); border: 1px solid rgba(150,180,215,.35); box-shadow: 0 4px 24px rgba(30,50,80,.14)` |
| `#dialog-text` | 浅紫文字 | `color: #1e2a3a` |
| `#name-tag` | 紫 | `background: rgba(208,224,244,.85); color: #24405e`（衬线体） |
| `#user-input` | 紫底紫字 | 浅色底 + `color:#1e2a3a` + 底部下划线 `border-bottom:1px solid rgba(150,180,215,.55)` |
| 按钮组（mic/send/expand/history/session/settings/favorites/replay） | 紫 | `color:#5b8cc4`，hover 淡蓝 |
| `#history-panel`/`#session-panel` 内容区 | 深紫毛玻璃 | `background: rgba(20,30,48,.90); border-color: rgba(140,170,210,.28)`；文字 `#dbe7f5` |
| `.history-msg` 气泡 | 紫系 | 面板深蓝灰系（浅蓝文字） |
| `.confirm-card`/`.app-toast` | 紫 | 深蓝灰面板 + 浅色文字；`.confirm-btn-ok` 保持红系 |
| `:root` | — | **不定义** `--font-title`/`--font-body` 默认值（纯由 JS `applyFontStyle` 设置，避免 "" 与 "serif" 同效）。CSS 规则中用 `var(--font-title)`/`var(--font-body)` 应用到 `#character-name`、`#dialog-text`、面板标题等全部文本承载元素（body、`.msg-bubble`、`.hint`/`.sub`、`.fav-text`、toast、confirm 卡片） |

- [ ] 2. `app.js` `applyConfig` 末尾加字体应用（`:root` 不定义默认变量，仅 JS 设置；`""` 回退浏览器默认）：

```javascript
function applyFontStyle(style) {
  var root = document.documentElement.style;
  if (style === "sans") {
    root.setProperty("--font-title", '"PingFang SC", "Noto Sans SC", "Microsoft YaHei", "Segoe UI", sans-serif');
    root.setProperty("--font-body", '"PingFang SC", "Noto Sans SC", "Microsoft YaHei", "Segoe UI", sans-serif');
  } else if (style === "") {
    root.removeProperty("--font-title");
    root.removeProperty("--font-body");
  } else {
    root.setProperty("--font-title", '"Noto Serif SC", "Source Han Serif SC", "Songti SC", "SimSun", Georgia, serif');
    root.setProperty("--font-body", '"PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif');
  }
}
```

`applyConfig(cfg)` 内调用 `applyFontStyle(cfg.font_style)`；`_handleComms` 增加：

```javascript
} else if (msg.kind === "font-change") {
  applyFontStyle(msg.style);
}
```

- [ ] 3. 视觉细节（审查修订）：`#dialog-text` text-shadow 改 none；`applyHistoryPalette` 移除暖偏移逻辑并冷化 fallback；对话框/角色名/按钮/输入行/面板移除 backdrop-filter；`.cursor`/`#user-input:focus`/`#background::after` 改冷色
- [ ] 4. 镜像复制 + MD5 校验（app.js/style.css 必须一致；index.html 无改动）

### Task 3: 设置页双端（字体选择 UI + 配色）

**Files:** `pages/settings/index.html`、`pages/settings/app.js`、`pages/settings/style.css`、`galgame_web/galgame/settings.html`

- [ ] 1. `index.html` 音量区后新增字体区：

```html
<div class="section active" id="section-font">
  <h2>字体</h2>
  <p class="hint">标题使用衬线体（宋体类），正文使用黑体，更接近日系视觉小说</p>
  <label class="font-option"><input type="radio" name="font-style" value="serif"> 默认（衬线标题 + 黑体正文）</label>
  <label class="font-option"><input type="radio" name="font-style" value="sans"> 全部黑体</label>
  <label class="font-option"><input type="radio" name="font-style" value=""> 系统默认</label>
</div>
```

- [ ] 2. `app.js`：`loadVolumePrefs`（或新 `loadFontPrefs`）读取 config.font_style 勾选对应 radio；change 事件保存。**通知链路（审查修订）**：Dashboard 版仅用 BroadcastChannel（复用现有 bgmChannel 长连接）；独立版仅用 `window.parent.postMessage`（现有 BGM 模式）；**不使用** `AstrBotPluginPage.postMessage`（API 不存在）；独立版**不加** BroadcastChannel（避免双投递）：

```javascript
var fontInputs = document.querySelectorAll('input[name="font-style"]');
fontInputs.forEach(function(input) {
  input.addEventListener("change", function() {
    apiPost("prefs", { font_style: this.value }).then(function() {
      notifyFontChange(this.value);
    }.bind(this)).catch(function(e) { setStatus("字体保存失败: " + e.message, "error"); });
  });
});
```

Dashboard 版 `notifyFontChange`（沿用 BGM 模式）:

```javascript
function notifyFontChange(style) {
  if (bgmChannel) { bgmChannel.postMessage({ kind: "font-change", style: style }); }
  applyFontStyleLocal(style);
}
```

独立版 `settings.html` 内 `notifyFontChange`（沿用 BGM 模式）:

```javascript
function notifyFontChange(style) {
  if (window.parent !== window) {
    window.parent.postMessage({ kind: "font-change", style: style }, "*");
  }
  applyFontStyleLocal(style);
}
```

（设置页自身应用字体：`applyFontStyleLocal` 同 Task 2 的 CSS 变量逻辑）

- [ ] 3. `style.css` / `settings.html` 内联 style：紫系 → 深蓝灰/浅色中性（`.section` 卡片、按钮、滑块、状态条）
- [ ] 4. 设置页自身字体：页面 `<style>` 中 body 使用 `--font-body` 变量，标题使用 `--font-title`；独立版 settings.html 相同

### Task 4: 收藏页双端（配色 + 取消收藏确认弹层）

**Files:** `pages/voice-favorites/index.html`、`pages/voice-favorites/app.js`、`galgame_web/galgame/favorites.html`

- [ ] 1. 配色：暖棕 → 冷调（`#fav-container` 深蓝灰 `rgba(20,30,48,.92)`、边框/文字浅蓝灰、`#fav-bg` 遮罩冷色）
- [ ] 2. `index.html`/`favorites.html`：新增 `#confirm-overlay` 弹层 DOM + 样式（复用 spec 色板；深蓝灰卡片 + 红确认按钮）
- [ ] 3. `app.js`/`favorites.html` 内联：加 `showConfirm`/`closeConfirm`/`_confirmOk`（与主页面实现一致，含 disabled 防双击 + `Promise.resolve().then(cb).finally(close)` + Esc/遮罩关闭）；`delBtn.onclick` 包 `showConfirm("取消收藏这条语音？", null, async function() { ...原逻辑... })`
- [ ] 4. 行为：双端取消收藏均弹确认

### Task 5: 验证

- [ ] `node --check` 全部改动 JS/HTML 内联脚本（PowerShell 提取内联 script 到临时文件后检查）
- [ ] galgame 双端 app.js/style.css MD5 一致；index.html 无改动
- [ ] `python -m pytest tests/ -q` 64 全绿；ruff 通过
- [ ] 残留扫描 `[^.\w](alert|confirm)\(` 零命中
- [ ] 手动清单：双端配色/字体切换即时生效/收藏确认/面板配色

### Task 6: 终审 + 版本 + 提交

- [ ] quality-reviewer-pro 终审（Level 2 final gate）
- [ ] `metadata.yaml` 0.8.0 → 0.8.1 + CHANGELOG v0.8.1 条目
- [ ] `git add` + commit（不 push）

---

## 自审

- Spec 覆盖：色板 ✓ 字体系统 ✓ prefs ✓ 收藏确认 ✓ 双端同步 ✓
- 关键契约：`applyFontStyle(style)` 三态（serif/sans/""）；`font_style` 枚举校验；弹层组件与主页面实现一致（防双击/自动关闭/Esc）
- 风险点：CSS 配色替换易遗漏——以 grep 紫色值（`#8b5cf6`/`rgba(.*,.*,255` 等）全量检查收尾
