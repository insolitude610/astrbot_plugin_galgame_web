# 删除确认弹层 + Toast 实施计划

> **For agentic workers:** 本计划已在设计阶段经三轮 solution-reviewer-pro 审查（VERDICT: PASS）。设计文档：`docs/superpowers/specs/2026-08-05-delete-confirmation-design.md`。实施后需 quality-reviewer-pro 终审。

**Goal:** 为插件全部删除操作添加自绘确认弹层，替换所有原生 confirm/alert，双端（Dashboard 内嵌页 + 独立 WebUI）行为一致。

**Architecture:** 每页内联 `showConfirm`/`showToast`（无共享依赖）；主页面快速点击检测排除弹层区域；孪生文件保持 MD5 一致。

**Tech Stack:** 原生 JS/CSS/HTML，无后端改动，无构建工具。

**基线:** main @ 87da6ed，64 测试全绿。

---

### Task 1: 主页面（双端孪生）

**Files:** `pages/galgame/app.js`、`pages/galgame/index.html`、`pages/galgame/style.css` → 改后复制到 `galgame_web/galgame/` 同名文件

- [ ] 1. `index.html` body 末尾加弹层 + toast DOM（`#confirm-overlay`/`#confirm-msg`/`#confirm-detail`/`#confirm-cancel`/`#confirm-ok`/`#app-toast`）
- [ ] 2. `style.css` 加 `.confirm-overlay`（z-index 1200）与 `.app-toast`（z-index 1300）样式
- [ ] 3. `app.js` 加 `showConfirm`/`closeConfirm`/`_confirmOk`/`showToast` 函数与事件绑定（Esc 关闭 + stopPropagation）
- [ ] 4. `app.js` 会话删除：抽 `deleteSession(sid, el)`，onclick 包 `showConfirm("删除该会话？", "AstrBot 对话记录与关联语音将一并清除，且无法恢复。", ...)`；catch 加 `showToast(..., "error")`
- [ ] 5. `app.js` 快速点击排除：click 排除列表加 `#confirm-overlay`；keydown 监听加目标排除
- [ ] 6. 复制三文件到 `galgame_web/galgame/`，验证 MD5 一致

关键代码（showConfirm 核心，三处内联实现以此为准）：

```javascript
function showConfirm(message, detail, onConfirm) {
  _confirmCb = onConfirm;
  var msgEl = document.getElementById("confirm-msg");
  var detEl = document.getElementById("confirm-detail");
  var okBtn = document.getElementById("confirm-ok");
  if (msgEl) msgEl.textContent = message;
  if (detEl) {
    detEl.textContent = detail || "";
    detEl.style.display = detail ? "" : "none";
  }
  document.getElementById("confirm-overlay").classList.add("active");
  if (okBtn) { okBtn.disabled = false; setTimeout(function() { okBtn.focus(); }, 50); }
}

function closeConfirm() {
  var ov = document.getElementById("confirm-overlay");
  if (ov) ov.classList.remove("active");
  _confirmCb = null;
}

function _confirmOk() {
  var okBtn = document.getElementById("confirm-ok");
  if (okBtn) okBtn.disabled = true;
  var cb = _confirmCb;
  if (typeof cb !== "function") { closeConfirm(); return; }
  Promise.resolve().then(function() { return cb(); }).finally(closeConfirm);
}

function showToast(msg, type) {
  var el = document.getElementById("app-toast");
  if (!el) return;
  if (_toastTimer) clearTimeout(_toastTimer);
  el.textContent = msg;
  el.className = "app-toast visible " + (type === "error" ? "toast-error" : "toast-success");
  _toastTimer = setTimeout(function() { el.classList.remove("visible"); }, 3000);
}
```

### Task 2: Dashboard 设置页

**Files:** `pages/settings/app.js`、`pages/settings/style.css`、`pages/settings/index.html`（如无独立 index 结构则 DOM 注入）

- [ ] 1. `app.js` 加 showConfirm/showToast 函数 + 绑定（弹层 DOM 若 index.html 无则动态创建）
- [ ] 2. `deleteFile`/`batchDeleteSelected`/`deleteBgm` 入口包 showConfirm（文案见 spec 4.5）
- [ ] 3. `deleteBgm` 成功路径加 `showToast("已删除: " + name, "success")`
- [ ] 4. `:408` alert → `showToast(..., "error")`
- [ ] 5. `style.css` 加弹层/toast 样式

### Task 3: 独立设置页

**Files:** `galgame_web/galgame/settings.html`（JS 内联单文件）

- [ ] 1. 内联 `<style>` 加弹层/toast 样式；body 加 DOM
- [ ] 2. 内联脚本加 showConfirm/showToast（与 Task 1 同实现）
- [ ] 3. `:360`/`:612`/`:979` 三处 `confirm(...)` → `showConfirm(同文案, null, ...)`
- [ ] 4. `:620` alert → showToast；BGM 删除成功加 toast

### Task 4: 收藏页双端

**Files:** `pages/voice-favorites/app.js`、`pages/voice-favorites/index.html`、`galgame_web/galgame/favorites.html`

- [ ] 1. Dashboard `app.js`：`:106` alert → showToast；index.html 加 toast DOM + 样式
- [ ] 2. 独立 `favorites.html`：**移除** `:279` confirm（改一键）；`:287` alert → showToast；加 toast 组件

### Task 5: 验证

- [ ] `node --check` 全部改动 JS/HTML 内联脚本
- [ ] grep 全项目 `confirm\(|alert\(` 零残留（排除 docs/CHANGELOG）
- [ ] galgame 双端三文件 MD5 一致
- [ ] `python -m pytest tests/ -q` 64 项全绿
- [ ] ruff check 通过

### Task 6: 终审 + 提交

- [ ] quality-reviewer-pro 终审（Level 2 final gate）
- [ ] `git add` + commit（不 push）：`feat: add delete confirmations and toast across WebUI`

---

## 自审

- Spec 覆盖：四项确认 ✓、收藏一键 ✓、alert→toast ✓、双端一致 ✓、快速点击排除 ✓
- 关键契约：`_confirmOk` 用 `Promise.resolve().then(onConfirm).finally(closeConfirm)`；确认按钮先 disabled；弹层 z-index 1200
- 双端一致：孪生文件复制后 MD5 校验；settings/favorites 双实现文案逐字一致
