# 2026-08-09 Backend Structure Refactor

> 纯结构重构，零用户可见行为变化。目标：拆分 `api/session.py` 上帝类、系统性消除 api↔main 循环导入、收敛 TTS 三段重复代码。为多角色 MVP Task 5（发送链路改造）铺路。

## 背景与问题（实测证据）

| 问题 | 证据 |
|------|------|
| 上帝类 | `api/session.py` 924 行 67 方法，混合会话端点/发送编排/管道推送/TTS/音频工具/编辑辅助 6 种职责 |
| main.py 臃肿 | 682 行中约 245 行是 TTS 实现（main.py:411-631），与生命周期/LLM 钩子无关 |
| 三段近似重复 | TTS provider 选择（session.py:890-898 ≈ main.py:434-440）；emotion_map 解析（session.py:882-888 ≈ main.py:426-432）；音频保存+mp3 转换（session.py:906-922 ≈ main.py:457-473） |
| 系统性循环导入 | 全部 7 个 api mixin 共 **23 处** 函数内 `from ..main import ...`（assets 8 处、session 3 处、bgm 5 处、favorites 3 处、config/prefs/audio 各 2/2/1 处） |
| 常量多源 | `AUDIO_DIR` 在 main.py:54 与 session_helpers.py:16 各定义一份；`FAVORITES_PATH` 同（main.py:56 vs session_helpers.py:17） |

## 目标结构

```
galgame_web/
├── session_helpers.py   # +3 常量（ASSETS_DIR/BGM_DIR/PREFS_PATH），接收 _load_prefs/_save_prefs
├── audio_utils.py       # ★新增：decode_audio_data / detect_audio_mime / ext_for_mime / save_audio / convert_audio
├── async_utils.py       # ★新增：run_in_thread_to_completion
├── tts.py               # ★新增：TTS 全家桶（含 synthesize_audio 核心收敛 + 临时文件自管理）
└── pipeline.py          # ★新增：push_through_pipeline / is_pure_json
```

- **单一真源原则**：所有路径常量（ASSETS_DIR/AUDIO_DIR/BGM_DIR/FAVORITES_PATH/PREFS_PATH）只在 `session_helpers.py` 定义；`_load_prefs/_save_prefs` 移到 session_helpers；`_convert_audio` 移到 audio_utils
- **api/ 层不再 import main**（23 处全部改源）
- **main.py 瘦身**：删 TTS 实现与模块级 TTS 工具；路径常量改 import；LLM 钩子改调 `tts.bg_tts`
- **api/session.py 瘦身**：删 6 个工具方法；`_do_send` 9 步编排、会话端点、`_edit_find_index/_edit_truncate` 原样保留；`_send_synthesize_tts` 保留签名改为调 `tts.synthesize_audio`

## 任务清单

### Task 1: session_helpers.py 扩展（路径真源 + prefs 函数）

- 新增：`ASSETS_DIR = _DATA / "assets"`、`BGM_DIR = _DATA / "bgm"`、`PREFS_PATH = _DATA / "prefs.json"`
- 移入：`_load_prefs()`（main.py:121-128，原样）、`_save_prefs(data)`（main.py:131-134，原样，内部 import 改同文件 `atomic_write_json`）

### Task 2: galgame_web/audio_utils.py（纯函数）

从 `api/session.py` 移入（原样，去掉 self）：
- `decode_audio_data(audio_data) -> bytes`（session.py:30-44）+ 常量 `MAX_VOICE_BYTES`/`MAX_VOICE_BASE64_CHARS`
- `detect_audio_mime(raw) -> str`（session.py:417-439）
- `ext_for_mime(mime) -> str` + `_MIME_EXT`（session.py:414-415, 16-23）
- `save_audio(raw) -> str`（session.py:537-544，temp 目录写入）

从 `main.py` 移入：
- `convert_audio(wav_path) -> Path | None`（main.py:137-151）

### Task 3: galgame_web/async_utils.py

- `run_in_thread_to_completion(func, *args)`（session.py:580-586，原样；shield + CancelledError 语义保持）

### Task 4: galgame_web/tts.py（核心收敛点）

**import 风格决策（评审 P0 修正）**：tts.py 内对 `AUDIO_DIR` 一律用 `from . import session_helpers` + 函数体内 `session_helpers.AUDIO_DIR` 属性访问（**动态读属性**，而非模块级 `from .session_helpers import AUDIO_DIR` 绑定）——保证测试 monkeypatch `session_helpers.AUDIO_DIR` 对 tts.py 生效，同时维持单一真源。

模块级移入（从 main.py）：
- `_TTS_TEMP_OUTPUTS`（main.py:59-61）、`_get_astrbot_temp_dir`（64-67）、`_cleanup_tts_temp_path`（70-92）、`_register_tts_temp_output`（95-102）、`_cleanup_tts_paths`（105-118）——内部 AUDIO_DIR 引用一律改 `session_helpers.AUDIO_DIR` 动态访问

函数（原样移入，去掉 self）：
- `split_sentences(text)`（main.py:484-486）
- `build_tagged_text(text, emotions, emotion_map)`（session.py:546-576）
- `build_sentence_tagged_texts(clean_text, emotions_all, emotion_map)`（main.py:488-514）
- `async parallel_tts(clean_text, emotions_all, emotion_map, tts_provider)`（main.py:516-581；内部 `_concat_audio` 改调 `async_utils.run_in_thread_to_completion`，签名保持 4 参数）
- `concat_audio(paths)`（main.py:583-630；`import subprocess` 在本模块，测试需 monkeypatch `tts_module.subprocess`）

收敛重复（provider 选择 + emotion_map 解析 + 保存/mp3 转换）：
- `select_tts_provider(config, context)`：收敛 session.py:890-898 与 main.py:434-440（`config.get("tts_provider")` → `context.provider_manager.inst_map.get(...)`；否则 `context.get_using_tts_provider()`）。**由各调用方显式调用**（评审第二轮 CE-7 修正）
- `parse_tts_emotion_map(config) -> dict`：收敛 session.py:882-888 与 main.py:426-432（json 解析 + 异常兜底）
- `async synthesize_audio(clean_text, emotions_all, tts_provider, config) -> (b64, mime, file)`：**纯 TTS 引擎**（评审第二轮 CE-7 修正：不含任何短路逻辑——tts_enabled/空文本/命令/无 provider 检查全部由调用方处理，因 `_send_synthesize_tts` 短路时必须保留 `pipeline_audio`）：
  - 内部自行 set/清理 `_TTS_TEMP_OUTPUTS`（替代 main.py:387-409 的 `_consume_tts_temp_outputs` 包装）：`tracked = []; token = _TTS_TEMP_OUTPUTS.set(tracked)` → try → finally 逐项 `_cleanup_tts_temp_path`
  - 流程：`parse_tts_emotion_map` → 防御性 `if not tts_provider: return "", "", ""` → `parallel_tts` → 保存 AUDIO_DIR + mp3 转换（收敛 session.py:906-922 与 main.py:457-473，mp3 判断读 `config.get("audio_format")`）→ 返回 (b64, mime, file)
  - 日志统一前缀 `[tts]`（评审第一轮 P2：bg/同步路径日志前缀差异属装饰性，API 契约不受影响）
- `async bg_tts(raw_text, session, config, context)`：main.py:411-482 的 `_do_bg_tts_impl` 主体移入，精确保留原分支（评审第二轮 CE-7 一致性）：
  1. raw_text 清洗（含 emotion 标签/括号/`<#...#>` 正则，main.py:416-418）；空文本 → `session["_bg_tts_result"] = ("", "", "")` 并 return（420-422）
  2. `extract_all_emotions`（424）
  3. `select_tts_provider(config, context)`；无 provider → `session["_bg_tts_result"] = ("", "", "")` 并 return（442-444）
  4. `await synthesize_audio(clean_text, emotions_all, tts_provider, config)` → `session["_bg_tts_result"] = 结果`（451-479 保存段收敛进 synthesize_audio；`[bg-tts]` debug 日志保留在 bg_tts）
  - **不自管理 contextvar**（评审第一轮 P2 修正）：所有临时文件生成均发生在所调用的 `synthesize_audio` 内部，由后者统一 set/清理；`bg_tts` 仅负责清洗、provider 解析与结果落位

**签名决策（评审第二轮 CE-7 修正）**：`synthesize_audio(clean_text, emotions_all, tts_provider, config)`——provider 已由调用方解析传入（纯引擎）；`bg_tts(raw_text, session, config, context)` 内部做 provider 解析与短路。`parallel_tts` 内部直接用 `async_utils.run_in_thread_to_completion`（不通过参数传入）。

### Task 5: galgame_web/pipeline.py

- `is_pure_json(text) -> bool`（session.py:441-449，原样）
- `async push_through_pipeline(config, username, session_id, text, audio_path) -> dict`（session.py:451-535 移入）：
  - 原方法体不变，`self.config` → `config` 参数，`self._webchat_username` → `username` 参数
  - 顶部加 `from astrbot.api import logger`（评审 P1：原方法体 6 处 logger 调用）
  - 内部 `from ..main import AUDIO_DIR` → 函数体内 `session_helpers.AUDIO_DIR` 动态访问（`from . import session_helpers`）
  - `self._detect_audio_mime/self._ext_for_mime` → `audio_utils.detect_audio_mime/ext_for_mime`
  - 返回结构 `{text, audio, audio_mime, audio_file}` 不变

### Task 6: api/session.py 瘦身

- 删除：模块级 `_decode_audio_data`（30-44）、`_MIME_EXT`/`_ext_for_mime`（16-23, 414-415）、`_detect_audio_mime`（417-439）、`_is_pure_json`（441-449）、`_save_audio`（537-544）、`_build_tagged_text`（546-576）、`_push_through_pipeline`（451-535）、`_run_in_thread_to_completion`（580-586）
- 删除 3 处 `from ..main import AUDIO_DIR`（454, 671, 866）→ 改调新模块/`session_helpers.AUDIO_DIR`
- `_send_synthesize_tts`（863-931）**保留方法签名与全部短路分支**（评审第二轮 CE-7 修正：短路必须返回 `pipeline_audio`，不能丢）：
  ```python
  async def _send_synthesize_tts(self, clean_text, emotions_all, text, matched_prefix, pipeline_audio):
      if not self.config.get("tts_enabled", True):
          return pipeline_audio, "", ""
      if not clean_text or matched_prefix:
          logger.debug(f"[tts] skipped text_len={len(clean_text)} command={'yes' if matched_prefix else 'no'}")
          return pipeline_audio, "", ""
      tts_provider = tts.select_tts_provider(self.config, self.context)
      if not tts_provider:
          logger.warning("[tts] No TTS provider configured, skipping TTS")
          return pipeline_audio, "", ""
      return await tts.synthesize_audio(clean_text, emotions_all, tts_provider, self.config)
  ```
- `_api_send`（588-636）：`_decode_audio_data` → `audio_utils.decode_audio_data`
- `_do_send`（638-726）：`_send_run_pipeline` 改调 `pipeline.push_through_pipeline(self.config, self._webchat_username, sid, text, audio_path)`；用户语音保存段（670-676）改 `audio_utils` 导入
- `_send_save_audio`（760-769）：`self._save_audio` → `audio_utils.save_audio`
- 会话端点、`_edit_find_index/_edit_truncate`、`_send_handle_command*`、`_send_extract_emotions`、`_send_save_and_return`、`_api_rapid_action` 等**不动**

### Task 7: 其余 6 个 api mixin 改 import 源（23 处循环导入消除）

- `assets.py`（8 处）：`ASSETS_DIR` → `from ..galgame_web.session_helpers import ASSETS_DIR`；`AUDIO_DIR`（193）同理
- `audio.py`（1 处）：AUDIO_DIR
- `bgm.py`（5 处）：BGM_DIR → session_helpers；`_load_prefs/_save_prefs`（83）→ session_helpers
- `config.py`（2 处）：ASSETS_DIR → session_helpers；`_load_prefs`（15）→ session_helpers
- `favorites.py`（3 处）：AUDIO_DIR/FAVORITES_PATH → session_helpers
- `prefs.py`（2 处）：`_load_prefs` → session_helpers；BGM_DIR → session_helpers

方法内局部 import 保持局部（运行时导入），仅换来源模块。

### Task 8: main.py 瘦身

- 删除模块级：`ASSETS_DIR/AUDIO_DIR/BGM_DIR/FAVORITES_PATH/PREFS_PATH` 定义（52-57，改从 session_helpers import）；`_TTS_TEMP_OUTPUTS`/`_get_astrbot_temp_dir`/`_cleanup_tts_temp_path`/`_register_tts_temp_output`/`_cleanup_tts_paths`（59-118）；`_load_prefs/_save_prefs`（121-134）；`_convert_audio`（137-151）
- 删除类方法：`_do_bg_tts`（397-400）、`_send_synthesize_tts`（402-409，SessionAPI override）、`_do_bg_tts_impl`（411-482）、`_split_sentences`（484-486）、`_build_sentence_tagged_texts`（488-514）、`_parallel_tts`（516-581）、`_concat_audio`（583-630）
- 保留：`_consume_tts_temp_outputs` 删除（被 tts 模块内管理取代）
- LLM 钩子 `_capture_llm_response`（351-354）：`self._do_bg_tts(text, session)` → `tts.bg_tts(text, session, self.config, self.context)`（保留 `self._track_task` 包装）
- import 行：session_helpers 导入集合扩充；顶部新增 `from .galgame_web import tts`（或 `from .galgame_web.tts import bg_tts`）
- `__init__`/`_start_web_server` 里常量使用不变（import 的常量）

### Task 9: 测试更新（语义不变，引用改源）

**新模块导入**（评审 P1）：`test_runtime_reliability.py` 顶部新增
```python
tts_module = importlib.import_module(f"{PACKAGE_NAME}.galgame_web.tts")
audio_utils = importlib.import_module(f"{PACKAGE_NAME}.galgame_web.audio_utils")
async_utils = importlib.import_module(f"{PACKAGE_NAME}.galgame_web.async_utils")
```
（`session_helpers` 已有导入）

| 文件 | 改动 |
|------|------|
| `test_input_limits.py` | `from api import session` → `from galgame_web.audio_utils import decode_audio_data, MAX_VOICE_BASE64_CHARS, MAX_VOICE_BYTES`；`session._decode_audio_data` → `decode_audio_data`；`monkeypatch session.MAX_VOICE_*` → `monkeypatch audio_utils.MAX_VOICE_*`（解码函数与常量同模块，模块级绑定生效） |
| `test_runtime_reliability.py` | `plugin._concat_audio`（355）→ `tts_module.concat_audio`；`plugin._parallel_tts`（389, 424）→ `tts_module.parallel_tts`（签名不变，4 参）；`plugin._do_bg_tts("...", session)`（476）→ `tts_module.bg_tts(text, session, config, context)`（fake config/context 含 `provider_manager.inst_map`/`get_using_tts_provider`）；`plugin._send_synthesize_tts`（485）→ `tts_module.synthesize_audio(clean_text, emotions_all, tts_provider, config)`（tts_provider 用该测试已有的 fake provider，实施时对齐 463-505 行上下文）；`api._detect_audio_mime`（102）→ `audio_utils.detect_audio_mime`；`api._run_in_thread_to_completion`（590）→ `async_utils.run_in_thread_to_completion`；`monkeypatch main_module.AUDIO_DIR`（339, 368, 409, 443, 501）→ `monkeypatch session_helpers.AUDIO_DIR`（tts.py 动态属性访问，生效）；`monkeypatch main_module._get_astrbot_temp_dir`（340, 369, 410, 444）→ `monkeypatch tts_module._get_astrbot_temp_dir`（评审 P0）；`monkeypatch main_module.subprocess.run`（347）→ `monkeypatch tts_module.subprocess.run`（评审 P0，`concat_audio` 的 ffmpeg 分支在 tts.py 内） |
| `test_session_behavior.py` | 192-196 的 `main_stub` mock 删除（favorites 不再 import main）；`_load_favorites` 依赖的 FAVORITES_PATH 改 monkeypatch `session_helpers.FAVORITES_PATH`（沿用 46 行已有模式；favorites.py 函数内 import 每次读当前模块属性，生效） |

其余 8 个测试文件不动。`_api_send/_send_handle_command/_send_save_and_return/_edit_find_index/_edit_truncate` 等方法位置不变，相关测试（test_session_behavior/test_message_editing）无需改动。

### Task 10: 验证

1. `python -m pytest tests/ -q`（全局 Python 3.12.2）全绿
2. ruff：`D:\AstrBotLauncher-0.1.5.5\AstrBot\venv\Scripts\python.exe -m ruff check .` + `ruff format .`
3. 导入冒烟（验证循环导入消除）：全局 Python 下 `python -c "import ast` 无法直接跑（依赖 astrbot mock）——用 pytest 自身的导入即验证（conftest 注入 mock 后所有模块加载成功）
4. 前端双端 MD5 校验（应无变化，纯后端改动）
5. git diff 走查：确认无行为逻辑改动（只搬运/改源/收敛）

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 搬运引入笔误 | 严格原样搬运，diff 走查对比 moved-from/moved-to；70+ 测试守门 |
| 测试对类方法的引用遗漏 | Task 9 清单基于 grep 全量枚举（26 处引用）；实施后跑 pytest 兜底 |
| TTS contextvar 清理语义变化 | `synthesize_audio/bg_tts` 内部复刻 `_consume_tts_temp_outputs` 的 set/finally-clean 语义；相关测试（临时文件清理用例）保持通过即证明 |
| 收敛合成函数时丢失分支行为 | 收敛只针对"provider 选择/emotion_map 解析/保存+mp3"三段，逐段对照原实现；`_send_synthesize_tts` 的 tts_enabled 短路与命令短路逻辑完整保留 |
| 测试 monkeypatch 目标失效 | Task 9 明确改为 monkeypatch session_helpers（单一真源），比 monkeypatch main 更稳定 |

## 提交策略

- 单个 commit：`refactor: split session API and centralize TTS/paths`（或按 Task 分组 2-3 个 commit）
- 版本号不变（重构不发布新版本），CHANGELOG 不新增条目——或经用户确认后加 `-` 维护性条目
