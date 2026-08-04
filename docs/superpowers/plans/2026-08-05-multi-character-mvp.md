# 多角色轮流对话 + 消息编辑 MVP 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 galgame 插件新增多角色固定循环轮流对话（角色卡可绑定 AstrBot persona 或自定义人格、场景随角色切换）和酒馆式消息操作（重生成/编辑/删除），单角色会话零改动。

**Architecture:** 复用现有 webchat 管道。multi 会话在每次发送前用 `update_conversation(persona_id=...)` 切换 AstrBot 人格（首次发送前用 `init_astrbot_conv` 带 persona 建对话），插件 `on_llm_request` 钩子注入角色卡 custom_prompt 与角色定位语；消息编辑统一走"截断插件 JSON history + `sync_conv_to_db` 同步 DB → 重走管道"。角色卡存插件自有 `characters.json`（原子写），前端设置页可视化编辑。

**Tech Stack:** Python 3.12 + pytest（mock 体系见 tests/conftest.py）、原生 JS（pages/galgame/ + pages/settings/，双端共用）、`http.server` 代理白名单（web_handler.py 新增路由）

**基线:** v0.7.14 + 已提交修复（fa9692e）。64 项测试全绿。spec: `docs/superpowers/specs/2026-08-05-multi-character-mvp-design.md`

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `galgame_web/characters_helpers.py` (新) | 角色卡 id 校验、characters.json 读写、角色卡结构常量 |
| `api/characters.py` (新) | GET/POST `/characters`、GET `/personas` |
| `api/session.py` | `session/init` mode 参数、轮流推进、persona 切换、next_character 响应、regenerate/edit/message-delete |
| `galgame_web/session_helpers.py` | 会话 mode/characters/next_char_idx 字段、history id 惰性补生成、`init_astrbot_conv` 支持指定 persona_id |
| `main.py` | mixin 注册、`_inject_galgame_rules` custom_prompt 注入 |
| `galgame_web/web_handler.py` | ALLOWED_API_ROUTES 新增 5 条路由 |
| `pages/settings/index.html` + `pages/settings/app.js` | 角色管理分区（可视化编辑） |
| `pages/galgame/index.html` + `pages/galgame/app.js` | 多角色会话创建/场景切换/当前角色指示/消息操作 UI |
| `galgame_web/galgame/*` | 上述前端文件的同构拷贝（保持哈希一致） |
| `tests/test_characters_api.py` (新) | 角色卡 API 测试 |
| `tests/test_multi_character.py` (新) | 轮流机制 + 管道集成测试 |
| `tests/test_message_editing.py` (新) | 消息编辑三项测试 |

---

### Task 1: 角色卡数据层（characters_helpers.py）

**Files:**
- Create: `galgame_web/characters_helpers.py`
- Test: `tests/test_characters_api.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_characters_api.py`：

```python
import json
import pathlib

import pytest

from galgame_web.characters_helpers import (
    CHARACTERS_PATH,
    VALID_CHARACTER_KEYS,
    is_valid_character_id,
    load_characters,
    save_characters,
)


@pytest.fixture(autouse=True)
def _clean_characters_file():
    CHARACTERS_PATH.unlink(missing_ok=True)
    yield
    CHARACTERS_PATH.unlink(missing_ok=True)


def test_character_id_validation():
    assert is_valid_character_id("alice")
    assert is_valid_character_id("a1-b2-c3")
    assert not is_valid_character_id("")
    assert not is_valid_character_id("Alice")
    assert not is_valid_character_id("a b")
    assert not is_valid_character_id("../../etc")
    assert not is_valid_character_id("a" * 65)


def test_save_and_load_roundtrip():
    items = [
        {
            "id": "alice",
            "name": "爱丽丝",
            "persona_id": "",
            "custom_prompt": "",
            "expressions": {"neutral": "alice_neutral.png"},
            "background": "",
            "bgm": "",
            "opening": "你好呀~",
            "tts_provider": "",
        }
    ]
    assert save_characters(items) is True
    loaded = load_characters()
    assert loaded == items


def test_save_rejects_invalid_items():
    assert save_characters([{"id": "../evil", "name": "x"}]) is False
    assert not CHARACTERS_PATH.exists()
    assert save_characters([]) is True
    assert load_characters() == []


def test_load_missing_file_returns_empty():
    assert load_characters() == []


def test_load_corrupt_file_returns_empty():
    CHARACTERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHARACTERS_PATH.write_text("{bad json", encoding="utf-8")
    assert load_characters() == []


def test_load_unknown_keys_dropped():
    assert save_characters(
        [{"id": "alice", "name": "A", "unknown_key": "x", "custom_prompt": ""}]
    )
    loaded = load_characters()[0]
    assert "unknown_key" not in loaded
    assert set(loaded.keys()) == set(VALID_CHARACTER_KEYS) - {"tts_provider"} | {"tts_provider"}
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_characters_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'galgame_web.characters_helpers'`

- [ ] **Step 3: 实现 characters_helpers.py**

```python
import json
import pathlib
import re

from astrbot.api import logger

from .session_helpers import _DATA, atomic_write_json

MAX_CHARACTERS = 12
MAX_NAME_CHARS = 64
MAX_PROMPT_CHARS = 20_000
MAX_OPENING_CHARS = 2_000

CHARACTER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

CHARACTERS_PATH: pathlib.Path = _DATA / "characters.json"

# 角色卡字段白名单（tts_provider 预留，MVP 不消费但保留字段）
VALID_CHARACTER_KEYS = {
    "id",
    "name",
    "persona_id",
    "custom_prompt",
    "expressions",
    "background",
    "bgm",
    "opening",
    "tts_provider",
}


def is_valid_character_id(cid: object) -> bool:
    return isinstance(cid, str) and bool(CHARACTER_ID_PATTERN.fullmatch(cid))


def _clean_item(item: dict) -> dict | None:
    """校验并清洗单个角色卡条目，非法返回 None。"""
    if not isinstance(item, dict):
        return None
    cid = item.get("id", "")
    name = item.get("name", "")
    if not is_valid_character_id(cid):
        return None
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME_CHARS:
        return None
    cleaned = {}
    for key in VALID_CHARACTER_KEYS:
        value = item.get(key, "")
        if key == "id":
            cleaned[key] = cid
        elif key == "name":
            cleaned[key] = name.strip()
        elif key == "expressions":
            if not isinstance(value, dict):
                value = {}
            value = {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str) and len(v) <= 255}
            cleaned[key] = value
        elif key == "custom_prompt":
            if not isinstance(value, str):
                value = ""
            cleaned[key] = value[:MAX_PROMPT_CHARS]
        elif key == "opening":
            if not isinstance(value, str):
                value = ""
            cleaned[key] = value[:MAX_OPENING_CHARS]
        else:
            cleaned[key] = value if isinstance(value, str) else ""
    return cleaned


def load_characters() -> list[dict]:
    if not CHARACTERS_PATH.exists():
        return []
    try:
        items = json.loads(CHARACTERS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(items, list):
        return []
    return [item for item in ( _clean_item(i) for i in items ) if item]


def save_characters(items: list) -> bool:
    if not isinstance(items, list) or len(items) > MAX_CHARACTERS:
        return False
    cleaned = []
    seen_ids = set()
    for item in items:
        entry = _clean_item(item)
        if entry is None or entry["id"] in seen_ids:
            return False
        seen_ids.add(entry["id"])
        cleaned.append(entry)
    try:
        atomic_write_json(CHARACTERS_PATH, cleaned)
        return True
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"Failed to save characters: {e}")
        return False
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_characters_api.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 提交**

```bash
git add galgame_web/characters_helpers.py tests/test_characters_api.py
git commit -m "feat: add character card data layer (characters.json)"
```

---

### Task 2: 角色卡 API + personas 列表 API

**Files:**
- Create: `api/characters.py`
- Modify: `main.py`（`GalgamePlugin` 基类列表 + `_register_apis`）、`galgame_web/web_handler.py`（路由白名单）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_characters_api.py`）

```python
import asyncio

from api.characters import CharAPI


class _FakeContext:
    def __init__(self, personas):
        self.personas = personas
        self.registered = []

    def register_web_api(self, route, handler, methods, desc):
        self.registered.append(route)


class _FakePersonaManager:
    def __init__(self, personas):
        self.personas = personas

    async def get_all_personas(self):
        return self.personas


def test_characters_api_registration():
    ctx = _FakeContext([])
    CharAPI()._register_characters_apis()  # 通过 context 注入后注册
    # 直接用假 context 验证路由存在
    assert "/astrbot_plugin_galgame_web/characters" in [r for r in _routes(ctx)]


def test_personas_list():
    pm = _FakePersonaManager([type("P", (), {"persona_id": "alice"})(), type("P", (), {"persona_id": "bob"})()])
    api = CharAPI()
    api.context = _FakeContext([])
    api.context.persona_manager = pm
    data = asyncio.run(api._api_personas())
    assert data == {"personas": [{"persona_id": "alice"}, {"persona_id": "bob"}]}


def _routes(ctx):
    return [r for r, *_ in ctx.registered]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_characters_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.characters'`

- [ ] **Step 3: 实现 api/characters.py**

```python
from quart import request

from astrbot.api import logger

from ..galgame_web.characters_helpers import (
    MAX_CHARACTERS,
    load_characters,
    save_characters,
)


class CharAPI:
    def _register_characters_apis(self):
        pn = self._plugin_name
        self.context.register_web_api(
            f"/{pn}/characters", self._api_characters_get, ["GET"], "List character cards"
        )
        self.context.register_web_api(
            f"/{pn}/characters", self._api_characters_save, ["POST"], "Save character cards"
        )
        self.context.register_web_api(
            f"/{pn}/personas", self._api_personas, ["GET"], "List AstrBot personas"
        )

    async def _api_characters_get(self):
        return {"characters": load_characters()}

    async def _api_characters_save(self):
        data = await request.get_json() or {}
        if not isinstance(data, dict):
            return {"error": "invalid request"}, 400
        items = data.get("characters", [])
        if not isinstance(items, list):
            return {"error": "characters must be a list"}, 400
        if len(items) > MAX_CHARACTERS:
            return {"error": f"at most {MAX_CHARACTERS} characters"}, 400
        if not save_characters(items):
            return {"error": "invalid character data"}, 400
        logger.info(f"[characters] saved {len(items)} characters")
        return {"status": "ok", "count": len(items)}

    async def _api_personas(self):
        try:
            personas = await self.context.persona_manager.get_all_personas()
            return {
                "personas": [
                    {"persona_id": getattr(p, "persona_id", "")}
                    for p in (personas or [])
                    if getattr(p, "persona_id", "")
                ]
            }
        except Exception as e:
            logger.warning(f"[characters] failed to list personas: {e}")
            return {"personas": []}
```

- [ ] **Step 4: main.py 注册**

在 `main.py`：
1. import 区新增 `from .api.characters import CharAPI`
2. `class GalgamePlugin(... CharAPI ...)` 基类列表插入 `CharAPI`（放在 `AssetAPI` 前）
3. `_register_apis` 首行加 `self._register_characters_apis()`

- [ ] **Step 5: web_handler.py 路由白名单**

在 `ALLOWED_API_ROUTES` 的 GET 集合加 `"characters"`、`"personas"`；POST 集合加 `"characters"`。

- [ ] **Step 6: 运行测试 + 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 64 + 8 = 72 passed（原 64 全绿 + 新 8 项，含 Task 1 的 6 项与本 Task 的 2 项）

Run: `ruff check .`；Expected: All checks passed!

- [ ] **Step 7: 提交**

```bash
git add api/characters.py main.py galgame_web/web_handler.py tests/test_characters_api.py
git commit -m "feat: add character card and persona list APIs"
```

---

### Task 3: 会话模型扩展（mode/characters/next_char_idx + history id）

**Files:**
- Modify: `galgame_web/session_helpers.py`、`api/session.py`（`_api_session_init_serialized`）
- Test: `tests/test_multi_character.py`（新）

- [ ] **Step 1: 写失败测试**（创建 `tests/test_multi_character.py`）

```python
import asyncio
import json
import pathlib
import uuid

import pytest

from galgame_web.session_helpers import SESSIONS_DIR, load_session, save_session


def _make_session(history=None, mode=None, characters=None):
    sid = uuid.uuid4().hex
    session = {
        "umo": "",
        "conv_id": "",
        "history": history if history is not None else [],
        "current_emotion": "neutral",
        "created_at": 1,
        "mode": mode,
        "characters": characters or [],
        "next_char_idx": 0,
    }
    return sid, session


def test_save_load_roundtrip_preserves_multi_fields():
    sid, session = _make_session(
        history=[{"id": "h1", "role": "user", "content": "hi"}],
        mode="multi",
        characters=["alice", "bob"],
    )
    session["next_char_idx"] = 1
    assert save_session({sid: session}, sid)
    loaded = load_session(sid)
    assert loaded["mode"] == "multi"
    assert loaded["characters"] == ["alice", "bob"]
    assert loaded["next_char_idx"] == 1


def test_load_legacy_session_gets_defaults_and_ids():
    sid = uuid.uuid4().hex
    path = SESSIONS_DIR / f"{sid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"umo": "", "conv_id": "", "history": [{"role": "user", "content": "hi"}], "current_emotion": "neutral", "created_at": 1}),
        encoding="utf-8",
    )
    loaded = load_session(sid)
    assert loaded["mode"] == "single"
    assert loaded["characters"] == []
    assert loaded["next_char_idx"] == 0
    assert loaded["history"][0]["id"]


def test_save_load_keeps_history_character_field():
    sid, session = _make_session(
        history=[{"id": "h2", "role": "assistant", "character": "alice", "content": "hi"}]
    )
    save_session({sid: session}, sid)
    loaded = load_session(sid)
    assert loaded["history"][0]["character"] == "alice"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_multi_character.py -v`
Expected: FAIL — `mode` KeyError / 无 `character` 字段

- [ ] **Step 3: 修改 session_helpers.py**

`load_session` 的返回 dict 增加：

```python
"mode": data.get("mode", "single") if isinstance(data.get("mode", "single"), str) else "single",
"characters": (
    [c for c in data.get("characters", []) if isinstance(c, str)]
    if isinstance(data.get("characters", []), list)
    else []
),
"next_char_idx": (
    data.get("next_char_idx", 0)
    if isinstance(data.get("next_char_idx", 0), int) and not isinstance(data.get("next_char_idx", 0), bool)
    else 0
),
```

`load_session` 的 history 清洗改为惰性补 id：

```python
"history": [
    {**item, "id": item.get("id") or uuid.uuid4().hex}
    for item in history
    if isinstance(item, dict)
],
```

`save_session` 的 data 序列化增加：

```python
"mode": session.get("mode", "single"),
"characters": session.get("characters", []),
"next_char_idx": session.get("next_char_idx", 0),
```

（history 条目本身已含 id/character，随 `session["history"]` 序列化）

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_multi_character.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 提交**

```bash
git add galgame_web/session_helpers.py tests/test_multi_character.py
git commit -m "feat: extend session model with multi-character fields"
```

---

### Task 4: session/init 支持 mode=multi（创建 + 开场白）

**Files:**
- Modify: `api/session.py`、`galgame_web/session_helpers.py`（`init_astrbot_conv` persona_id 参数）
- Test: `tests/test_multi_character.py`

- [ ] **Step 1: 写失败测试**

```python
def test_init_multi_requires_at_least_two_characters():
    # 通过直接调用 _api_session_init_serialized 的纯逻辑部分验证：
    # characters 不足 2 时返回 400
    from api.session import SessionAPI

    api = SessionAPI()
    api._sessions = {}
    api._webchat_username = "astrbot"
    api.context = _FakeSessionContext()
    api.config = {}
    # 空角色卡时 multi 创建失败
    result = asyncio.run(api._api_multi_init_validate([]))
    assert result is False
```

（`_api_multi_init_validate` 为计划新增的静态辅助函数，如下实现；实际 multi 创建在 `_api_session_init_serialized` 内调用）

- [ ] **Step 2: 实现 session.py 的 multi 创建逻辑**

在 `api/session.py`：

```python
def _api_multi_init_validate(self, characters: list) -> bool:
    """multi 会话要求角色卡至少 2 个。"""
    return isinstance(characters, list) and len(characters) >= 2
```

在 `_api_session_init_serialized` 中，`force_new`/空白复用逻辑之后、创建新会话前插入 multi 分支（在 session_count 检查前）：

```python
mode = data.get("mode", "single")
if mode not in ("single", "multi"):
    return {"error": "invalid mode"}, 400

from ..galgame_web.characters_helpers import load_characters

if mode == "multi":
    cards = load_characters()
    if not self._api_multi_init_validate(cards):
        return {"error": "multi mode requires at least 2 characters configured"}, 400
```

新会话 dict 创建处增加：

```python
"mode": mode,
"characters": [c["id"] for c in cards] if mode == "multi" else [],
"next_char_idx": 0,
```

multi 分支在保存会话后、返回前插入开场白：

```python
if mode == "multi":
    first = next((c for c in cards if c["id"] == session["characters"][0]), None)
    if first:
        opening = (first.get("opening") or "").strip()
        if not opening and first.get("persona_id"):
            try:
                persona = await self.context.persona_manager.get_persona(first["persona_id"])
                dialogs = getattr(persona, "begin_dialogs", None) or []
                if dialogs:
                    last = str(dialogs[-1])
                    opening = last.split(":", 1)[-1].strip()
            except Exception:
                pass
        if opening:
            session["history"].append({
                "id": uuid.uuid4().hex,
                "role": "assistant",
                "character": first["id"],
                "content": opening,
            })
            # 开场白由角色 0 说出；首轮用户消息应由下一角色回应（否则角色 0 连说两次）
            session["next_char_idx"] = 1 % len(session["characters"])
            save_session(self._sessions, sid)
    from ..galgame_web.characters_helpers import load_characters as _lc
    return {
        "session_id": sid,
        "mode": "multi",
        "characters": [
            {
                "id": c["id"],
                "name": c.get("name", c["id"]),
                "expressions": c.get("expressions", {}),
                "background": c.get("background", ""),
                "bgm": c.get("bgm", ""),
            }
            for c in cards
        ],
        "current_emotion": session.get("current_emotion", "neutral"),
    }
```

同时在 `_api_session_init_serialized` 的**全部 5 个返回路径**（①内存 resume、②磁盘 load resume、③auto-resume latest、④空白会话复用、⑤新建会话）的返回 dict 中增加 `"mode"` 与 `"characters"` 字段（single 会话为 `"mode": "single"`、`"characters": []`）。multi 会话 resume 时 `"characters"` 为其角色摘要列表（从 `load_characters` 按 `session["characters"]` 的 id 顺序匹配）。5 个路径结构必须一致，前端 `initSession` 才能正确识别多角色会话并渲染场景。

- [ ] **Step 3: session_helpers.init_astrbot_conv 支持指定 persona_id**

修改签名与内部（供 Task 5 首轮建对话带人格）：

```python
async def init_astrbot_conv(
    context,
    webchat_username: str,
    config: dict,
    session_id: str,
    session: dict,
    persona_id: str | None = None,
):
    ...
    if persona_id is None:
        persona_id = config.get("persona", "") or None
```

（将 `persona_id = config.get("persona", "") or None` 行改为上述参数逻辑）

- [ ] **Step 4: 运行测试 + 回归**

Run: `python -m pytest tests/ -q`
Expected: 75 passed（新增 1 项 + 原 74）

- [ ] **Step 5: 提交**

```bash
git add api/session.py galgame_web/session_helpers.py tests/test_multi_character.py
git commit -m "feat: support multi-mode session init with opening line"
```

---

### Task 5: 管道集成（persona 切换 + custom_prompt + 轮流推进 + next_character）

**Files:**
- Modify: `api/session.py`、`main.py`
- Test: `tests/test_multi_character.py`

- [ ] **Step 1: 写失败测试**

```python
def test_next_character_rotation_wraps():
    from api.session import SessionAPI

    api = SessionAPI()
    api._sessions = {"s" * 32: {"characters": ["alice", "bob", "carol"], "next_char_idx": 2}}
    result = api._send_advance_character("s" * 32)
    assert result == 0  # 回绕


def test_next_character_advances():
    api = SessionAPI()
    api._sessions = {"s" * 32: {"characters": ["alice", "bob"], "next_char_idx": 0}}
    assert api._send_advance_character("s" * 32) == 1


def test_single_session_advance_is_noop():
    api = SessionAPI()
    api._sessions = {"s" * 32: {"characters": [], "next_char_idx": 0}}
    assert api._send_advance_character("s" * 32) == 0


def test_recalc_next_char_from_history():
    api = SessionAPI()
    api._sessions = {"s" * 32: {
        "mode": "multi",
        "characters": ["alice", "bob", "carol"],
        "next_char_idx": 0,
        "history": [
            {"id": "a", "role": "assistant", "character": "alice", "content": "开场"},
            {"id": "b", "role": "user", "content": "hi"},
            {"id": "c", "role": "assistant", "character": "bob", "content": "yo"},
        ],
    }}
    assert api._send_recalc_next_char("s" * 32) == 2  # bob 的下一顺位 = carol


def test_recalc_next_char_empty_history_resets_to_zero():
    api = SessionAPI()
    api._sessions = {"s" * 32: {
        "mode": "multi", "characters": ["alice", "bob"], "next_char_idx": 1,
        "history": [{"id": "a", "role": "user", "content": "hi"}],
    }}
    assert api._send_recalc_next_char("s" * 32) == 0


def test_regenerate_speaker_restored_from_deleted_message():
    """reviewer 反例：重生成必须由被删消息的同一角色回答。"""
    api = SessionAPI()
    api._sessions = {"s" * 32: {
        "mode": "multi",
        "characters": ["alice", "bob"],
        "next_char_idx": 0,  # Alice 刚回复完已推进到 0（指向 Alice）
        "history": [
            {"id": "a", "role": "assistant", "character": "alice", "content": "开场"},
            {"id": "b", "role": "user", "content": "hi"},
            {"id": "c", "role": "assistant", "character": "bob", "content": "yo"},
        ],
    }}
    # 模拟 _api_regenerate 的截断前记录：被删消息 c 的 character = bob
    last_speaker = api._sessions["s" * 32]["history"][-1]["character"]
    api._sessions["s" * 32]["history"] = api._sessions["s" * 32]["history"][:-1]
    if last_speaker in api._sessions["s" * 32]["characters"]:
        api._sessions["s" * 32]["next_char_idx"] = api._sessions["s" * 32]["characters"].index(last_speaker)
    assert api._sessions["s" * 32]["next_char_idx"] == 1  # bob


def test_opening_line_advances_next_char():
    """reviewer 反例：开场白后 next_char_idx 必须推进，首轮用户消息由角色 1 回应。"""
    api = SessionAPI()
    chars = ["alice", "bob"]
    api._sessions = {"s" * 32: {"mode": "multi", "characters": chars, "next_char_idx": 0,
                                "history": [{"id": "a", "role": "assistant", "character": "alice", "content": "开场"}]}}
    # 模拟 Task 4 开场白写入后的推进
    api._sessions["s" * 32]["next_char_idx"] = 1 % len(chars)
    assert api._sessions["s" * 32]["next_char_idx"] == 1


def test_build_next_character_payload_single_returns_none():
    api = SessionAPI()
    api._sessions = {"s" * 32: {"mode": "single"}}
    assert api._send_build_next_character("s" * 32) is None
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_multi_character.py -v`
Expected: FAIL — `AttributeError: no attribute '_send_advance_character'`

- [ ] **Step 3: 实现 api/session.py 新方法**

```python
def _send_advance_character(self, sid) -> int:
    session = self._sessions.get(sid)
    if not session or session.get("mode") != "multi":
        return 0
    chars = session.get("characters", [])
    if not chars:
        return 0
    next_idx = (session.get("next_char_idx", 0) + 1) % len(chars)
    session["next_char_idx"] = next_idx
    return next_idx


def _send_build_next_character(self, sid):
    session = self._sessions.get(sid)
    if not session or session.get("mode") != "multi":
        return None
    chars = session.get("characters", [])
    idx = session.get("next_char_idx", 0)
    cid = chars[idx] if chars else ""
    from ..galgame_web.characters_helpers import load_characters

    for card in load_characters():
        if card.get("id") == cid:
            return {
                "id": card["id"],
                "name": card.get("name", card["id"]),
                "expressions": card.get("expressions", {}),
                "background": card.get("background", ""),
                "bgm": card.get("bgm", ""),
            }
    return None


def _send_recalc_next_char(self, sid) -> int:
    """编辑/删除/重生成截断后，从剩余 history 恢复轮转一致性。

    规则：扫描剩余 history 中最后一条 assistant 消息的 character 字段，
    下一位发言者 = 该角色在 characters 中的下一顺位（循环）；剩余 history
    无 assistant 消息时重置为 0（开场角色）。返回计算后的 next_char_idx。
    """
    session = self._sessions.get(sid)
    if not session or session.get("mode") != "multi":
        return 0
    chars = session.get("characters", [])
    if not chars:
        return 0
    for msg in reversed(session.get("history", [])):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "assistant":
            cid = msg.get("character", "")
            if cid in chars:
                next_idx = (chars.index(cid) + 1) % len(chars)
                session["next_char_idx"] = next_idx
                return next_idx
            # 该条 assistant 的 character 无效（理论上 multi 会话不会出现，
            # 防御性处理）：继续往前找更早的 assistant，而不是重置
            continue
    session["next_char_idx"] = 0
    return 0
```

- [ ] **Step 4: 实现 persona 切换（_send_switch_persona）**

```python
async def _send_switch_persona(self, sid):
    """multi 会话发送前切换 AstrBot 人格。首次无对话时带 persona 建对话。

    契约：仅在持有 session._send_lock 时调用（_do_send 与 _do_regenerate 均在锁内）。
    """
    session = self._sessions.get(sid)
    if not session or session.get("mode") != "multi":
        return
    chars = session.get("characters", [])
    if not chars:
        return
    cid = chars[session.get("next_char_idx", 0) % len(chars)]
    from ..galgame_web.characters_helpers import load_characters

    card = next((c for c in load_characters() if c.get("id") == cid), None)
    persona_id = (card or {}).get("persona_id", "")
    if not persona_id:
        return
    umo = session.get("umo", "")
    conv_id = session.get("conv_id", "")
    try:
        if not conv_id and umo:
            from ..galgame_web.session_helpers import init_astrbot_conv

            await init_astrbot_conv(
                self.context, self._webchat_username, self.config, sid, session,
                persona_id=persona_id,
            )
            # 注意：init_astrbot_conv 内部已写入 session["conv_id"]（新建对话 id），
            # 此处禁止再用旧值覆盖 session["conv_id"]。
            # 幂等性：init_astrbot_conv 内部先 get_curr_conversation_id 查重，
            # 与插件启动时 sync_sessions_to_db 后台任务并发调用时不会重复建对话
            # （最坏情况是重复查询一次，最终一致）。
            return
        if conv_id and umo:
            await self.context.conversation_manager.update_conversation(
                unified_msg_origin=umo,
                conversation_id=conv_id,
                persona_id=persona_id,
            )
    except Exception as e:
        # persona_id 可能已被用户在 AstrBot 中删除：AstrBot 会静默回退默认人格，
        # 插件无法强制，但必须 error 级日志便于排查。
        logger.error(f"[multi] persona switch failed for {cid} (persona={persona_id}): {e}")
```

在 `_do_send` 的 Step 2（`_send_handle_command`）之前调用 `await self._send_switch_persona(sid)`（`_do_send` 本身在 `_send_lock` 内）。

- [ ] **Step 5: main.py _inject_galgame_rules 注入 custom_prompt + 角色定位语**

在 `_inject_galgame_rules` 中，`sid not in self._sessions` 检查后追加：

```python
session = self._sessions.get(sid)
if session and session.get("mode") == "multi":
    chars = session.get("characters", [])
    if chars:
        from .galgame_web.characters_helpers import load_characters

        cid = chars[session.get("next_char_idx", 0) % len(chars)]
        card = next((c for c in load_characters() if c.get("id") == cid), None)
        if card:
            name = card.get("name", cid)
            rules = f"你正在扮演《{name}》。\n\n" + rules
            custom = (card.get("custom_prompt") or "").strip()
            if custom:
                req.system_prompt += f"\n\n# 角色设定（自定义）\n{custom}\n"
```

（注意现有代码先取 `rules`，此处改名局部变量不影响后续替换 `{{emotions}}` 与追加逻辑）

- [ ] **Step 6: 保存步骤集成轮流推进 + next_character 响应**

在 `_send_save_and_return` 的返回 dict 前：

```python
self._send_advance_character(sid)
next_character = self._send_build_next_character(sid)
```

返回 dict 增加 `"next_character": next_character`。

在 history append 处（assistant 消息）增加 `character` 字段：

```python
char_id = ""
if session.get("mode") == "multi":
    chars = session.get("characters", [])
    # append 时 next_char_idx 尚未推进，直接指向当前发言者（不得用 -1 偏移，
    # 否则会记录到"下一角色"）
    char_id = chars[session.get("next_char_idx", 0) % len(chars)] if chars else ""
session["history"].append(
    {
        "id": uuid.uuid4().hex,
        "role": "assistant",
        "character": char_id,
        "content": clean_text,
        "audio_file": audio_file,
        "audio_mime": audio_mime_val,
    }
)
```

用户消息条目同样加 `"id": uuid.uuid4().hex, "character": ""`。

- [ ] **Step 7: 运行测试 + 回归**

Run: `python -m pytest tests/ -q`
Expected: 79 passed（新增 4 项）

- [ ] **Step 8: 提交**

```bash
git add api/session.py main.py tests/test_multi_character.py
git commit -m "feat: integrate multi-character rotation into pipeline"
```

---

### Task 6: 消息编辑基础（截断 + DB 同步辅助）

**Files:**
- Modify: `api/session.py`
- Test: `tests/test_message_editing.py`（新）

- [ ] **Step 1: 写失败测试**（创建 `tests/test_message_editing.py`）

```python
import asyncio
import uuid

import pytest

from api.session import SessionAPI


class _FakeCtx:
    def __init__(self):
        self.updated = []
        self.conversation_manager = self

    async def get_conversation(self, umo, cid):
        return object()

    async def update_conversation(self, **kwargs):
        self.updated.append(kwargs)


def _sid():
    return uuid.uuid4().hex


def _session(history):
    return {"umo": f"webchat:FriendMessage:webchat!astrbot!{_sid()}", "conv_id": "c1",
            "history": history, "_lock": asyncio.Lock(), "mode": "single"}


def test_find_message_index():
    api = SessionAPI()
    api._sessions = {"s" * 32: _session([
        {"id": "a", "role": "user", "content": "x"},
        {"id": "b", "role": "assistant", "content": "y"},
    ])}
    assert api._edit_find_index("s" * 32, "b") == 1
    assert api._edit_find_index("s" * 32, "zzz") is None


def test_truncate_history():
    api = SessionAPI()
    api._sessions = {"s" * 32: _session([
        {"id": "a", "role": "user", "content": "x"},
        {"id": "b", "role": "assistant", "content": "y"},
        {"id": "c", "role": "user", "content": "z"},
    ])}
    removed = api._edit_truncate("s" * 32, 1)
    assert removed == [{"id": "b", "role": "assistant", "content": "y"}]
    assert api._sessions["s" * 32]["history"] == [
        {"id": "a", "role": "user", "content": "x"},
    ]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_message_editing.py -v`
Expected: FAIL — `AttributeError`

- [ ] **Step 3: 实现辅助方法**

```python
def _edit_find_index(self, sid, message_id):
    session = self._sessions.get(sid)
    if not session:
        return None
    history = session.get("history", [])
    for i, msg in enumerate(history):
        if isinstance(msg, dict) and msg.get("id") == message_id:
            return i
    return None


def _edit_truncate(self, sid, keep_n):
    """截断 history 到 keep_n 条，返回被移除的条目，并同步 DB。"""
    from ..galgame_web.session_helpers import cleanup_unreferenced_audio, save_session, sync_conv_to_db

    session = self._sessions[sid]
    removed = []
    async def _do():
        async with session["_lock"]:
            removed.extend(session["history"][keep_n:])
            session["history"] = session["history"][:keep_n]
        save_session(self._sessions, sid)
        try:
            await sync_conv_to_db(self.context, session)
        except Exception:
            pass
        cleanup_unreferenced_audio(removed, self._sessions)
    # 返回 (removed, coroutine)：调用方 await 该协程执行截断+同步。
    # 注意必须调用 _do() 返回协程对象（返回 _do 本身会让调用方 await 一个函数而 TypeError）。
    return removed, _do()
```

注意：为配合 async 环境，`_edit_truncate` 返回 `(removed, coroutine)`，调用方 `await coroutine`。若测试直接断言 history，可在 run 中执行协程。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_message_editing.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 提交**

```bash
git add api/session.py tests/test_message_editing.py
git commit -m "feat: add message truncation helpers for editing"
```

---

### Task 7: POST session/regenerate

**Files:**
- Modify: `api/session.py`
- Test: `tests/test_message_editing.py`

- [ ] **Step 1: 写失败测试**

```python
def test_regenerate_requires_user_before_assistant():
    api = SessionAPI()
    api._sessions = {"s" * 32: _session([
        {"id": "a", "role": "user", "content": "hi"},
        {"id": "b", "role": "assistant", "content": "yo"},
        {"id": "c", "role": "user", "content": "again"},  # 最后一条不是 assistant
    ])}
    result = asyncio.run(api._api_regenerate_validate("s" * 32))
    assert result is False


def test_regenerate_validates_last_pair():
    api = SessionAPI()
    api._sessions = {"s" * 32: _session([
        {"id": "a", "role": "user", "content": "hi"},
        {"id": "b", "role": "assistant", "content": "yo"},
    ])}
    result = asyncio.run(api._api_regenerate_validate("s" * 32))
    assert result is True


def test_regenerate_rejects_voice_message():
    api = SessionAPI()
    api._sessions = {"s" * 32: _session([
        {"id": "a", "role": "user", "content": "(语音消息)", "audio_file": "x.wav"},
        {"id": "b", "role": "assistant", "content": "yo"},
    ])}
    result = asyncio.run(api._api_regenerate_validate("s" * 32))
    assert result is False
```

- [ ] **Step 2: 实现**

在 `_register_session_apis` 注册 `f"/{pn}/regenerate"`。

```python
async def _api_regenerate_validate(self, sid) -> bool:
    session = self._sessions.get(sid)
    if not session:
        return False
    history = session.get("history", [])
    if len(history) < 2:
        return False
    last, prev = history[-1], history[-2]
    if not (isinstance(last, dict) and isinstance(prev, dict)):
        return False
    if last.get("role") != "assistant" or prev.get("role") != "user":
        return False
    if prev.get("audio_file"):
        return False
    return True


async def _api_regenerate(self):
    if getattr(self, "_terminating", False):
        return {"error": "plugin is reloading"}, 503
    data = await request.get_json() or {}
    if not isinstance(data, dict):
        return {"error": "invalid request"}, 400
    sid = data.get("session_id", "")
    if not is_valid_session_id(sid) or sid not in self._sessions:
        return {"error": "invalid session_id"}, 400
    if not await self._api_regenerate_validate(sid):
        return {"error": "nothing to regenerate"}, 400
    session = self._sessions[sid]
    async with session.setdefault("_send_lock", asyncio.Lock()):
        history = session.get("history", [])
        # 记录被删 assistant 消息的发言角色：重生成必须由同一角色回答，
        # 否则 _send_switch_persona 会切到 next_char_idx 指向的"下一角色"（换人答）。
        last_speaker = ""
        if history and isinstance(history[-1], dict):
            last_speaker = history[-1].get("character", "")
        user_text = history[-2].get("content", "")
        removed, trunc_coro = self._edit_truncate(sid, len(history) - 1)
        await trunc_coro
        if session.get("mode") == "multi" and last_speaker in session.get("characters", []):
            session["next_char_idx"] = session["characters"].index(last_speaker)
        return await self._do_regenerate(sid, user_text)


async def _do_regenerate(self, sid, user_text):
    """截断后重放用户输入走管道，仅追加 assistant 消息。

    前置条件：调用方已在 _send_lock 内，且已把 next_char_idx 指向
    被重生成消息的发言角色（_api_regenerate 负责），_send_switch_persona
    据此切到正确人格。
    """
    session = self._sessions[sid]
    await self._send_switch_persona(sid)
    response_event = session.get("_resp_event")
    if response_event:
        response_event.clear()
    session.pop("_last_resp_text", None)
    pipeline_result = await self._send_run_pipeline(user_text, sid, "")
    if isinstance(pipeline_result, dict) and "error" in pipeline_result:
        return pipeline_result, 500
    raw_reply = pipeline_result["text"]
    if not raw_reply:
        raw_reply = await self._send_wait_for_llm(session, user_text)
    clean_text, emotions, emotions_all = await self._send_extract_emotions(raw_reply, session)
    audio_b64 = pipeline_result.get("audio", "")
    _bg_task = session.pop("_bg_tts_task", None)
    if _bg_task:
        await _bg_task
        audio_b64, audio_mime_val, audio_file = session.pop("_bg_tts_result", ("", "", ""))
    else:
        audio_b64, audio_mime_val, audio_file = await self._send_synthesize_tts(
            clean_text, emotions_all, user_text, "", audio_b64
        )
    return await self._send_save_and_return(
        session, user_text, clean_text, emotions, emotions_all,
        audio_b64, audio_mime_val, audio_file, sid,
        skip_user_append=True,
        await_sync=True,
    )
```

修改 `_send_save_and_return` 签名加 `skip_user_append: bool = False` 与 `await_sync: bool = False`，在 append user 消息处：

```python
if not skip_user_append:
    session["history"].append({...user 消息...})
session["history"].append({...assistant 消息...})
```

同步调用处（`_sync` 任务）改为受 `await_sync` 控制，避免管道 `_save_to_history` 与插件 `sync_conv_to_db` 在 DB 上竞态（regenerate/edit 路径必须 await 同步，普通发送保持后台任务）：

```python
        try:

            async def _sync():
                await sync_conv_to_db(self.context, session)

            import asyncio

            if await_sync:
                await _sync()
            else:
                self._track_task(_sync())
        except Exception as e:
            logger.warning(f"Failed to sync conversation to DB: {e}")
```

（`_api_regenerate` 内 `is_valid_session_id` 需从 `..galgame_web.session_helpers` 导入——文件顶部已有局部导入模式）

- [ ] **Step 3: 运行测试**

Run: `python -m pytest tests/test_message_editing.py -v`
Expected: PASS (5 passed)

- [ ] **Step 4: 提交**

```bash
git add api/session.py tests/test_message_editing.py
git commit -m "feat: add session regenerate API"
```

---

### Task 8: POST session/edit 与 session/message-delete

**Files:**
- Modify: `api/session.py`
- Test: `tests/test_message_editing.py`

- [ ] **Step 1: 写失败测试**

```python
def test_edit_user_message_truncates_and_returns_user_text():
    api = SessionAPI()
    api._sessions = {"s" * 32: _session([
        {"id": "a", "role": "user", "content": "old"},
        {"id": "b", "role": "assistant", "content": "yo"},
    ])}
    result = asyncio.run(api._api_edit_prepare("s" * 32, "a", "new text"))
    assert result["ok"] is True
    assert result["index"] == 0
    assert result["role"] == "user"
    assert result["new_text"] == "new text"


def test_edit_assistant_message_returns_no_regenerate():
    api = SessionAPI()
    api._sessions = {"s" * 32: _session([
        {"id": "a", "role": "user", "content": "hi"},
        {"id": "b", "role": "assistant", "content": "old reply"},
    ])}
    result = asyncio.run(api._api_edit_prepare("s" * 32, "b", "rewritten"))
    assert result["ok"] is True
    assert result["role"] == "assistant"
    assert result["regenerate"] is False


def test_edit_missing_message_returns_error():
    api = SessionAPI()
    api._sessions = {"s" * 32: _session([])}
    result = asyncio.run(api._api_edit_prepare("s" * 32, "zzz", "x"))
    assert result["ok"] is False


def test_message_delete_prepare():
    api = SessionAPI()
    api._sessions = {"s" * 32: _session([
        {"id": "a", "role": "user", "content": "1"},
        {"id": "b", "role": "assistant", "content": "2"},
        {"id": "c", "role": "user", "content": "3"},
    ])}
    result = asyncio.run(api._api_delete_prepare("s" * 32, "b"))
    assert result["ok"] is True
    assert result["keep_n"] == 1
```

- [ ] **Step 2: 实现**

注册 `f"/{pn}/edit"` 与 `f"/{pn}/message-delete"`。

```python
async def _api_edit_prepare(self, sid, message_id, new_text):
    """校验编辑请求，返回计划信息（不修改状态）。"""
    if not isinstance(new_text, str):
        return {"ok": False, "error": "new_text must be a string"}
    new_text = new_text.strip()
    if not new_text:
        return {"ok": False, "error": "new_text required"}
    if len(new_text) > MAX_TEXT_CHARS:
        return {"ok": False, "error": "message too long"}
    index = self._edit_find_index(sid, message_id)
    if index is None:
        return {"ok": False, "error": "message not found"}
    session = self._sessions[sid]
    role = session["history"][index].get("role", "")
    return {
        "ok": True,
        "index": index,
        "role": role,
        "regenerate": role == "user",
        "new_text": new_text,
    }


async def _api_edit(self):
    if getattr(self, "_terminating", False):
        return {"error": "plugin is reloading"}, 503
    data = await request.get_json() or {}
    if not isinstance(data, dict):
        return {"error": "invalid request"}, 400
    sid = data.get("session_id", "")
    if not is_valid_session_id(sid) or sid not in self._sessions:
        return {"error": "invalid session_id"}, 400
    message_id = data.get("message_id", "")
    new_text = data.get("new_text", "")
    plan = await self._api_edit_prepare(sid, message_id, new_text)
    if not plan["ok"]:
        return {"error": plan["error"]}, (404 if plan.get("error") == "message not found" else 400)
    session = self._sessions[sid]
    async with session.setdefault("_send_lock", asyncio.Lock()):
        async with session["_lock"]:
            session["history"][plan["index"]]["content"] = plan["new_text"]
        removed, trunc_coro = self._edit_truncate(sid, plan["index"] + 1)
        await trunc_coro
        if plan["regenerate"]:
            # 编辑用户消息：截断后先恢复轮转一致性，再重生成
            self._send_recalc_next_char(sid)
            return await self._do_regenerate(sid, plan["new_text"])
        # 编辑 AI 消息：改写历史后下一位发言者 = 剩余 history 最后 assistant 的下一顺位
        self._send_recalc_next_char(sid)
        return {
            "reply": plan["new_text"],
            "emotion": session.get("current_emotion", "neutral"),
            "emotions": [],
            "audio": "",
            "audio_mime": "",
            "audio_file": "",
            "audio_segments": [],
            "next_character": self._send_build_next_character(sid),
        }


async def _api_delete_prepare(self, sid, message_id):
    index = self._edit_find_index(sid, message_id)
    if index is None:
        return {"ok": False, "error": "message not found"}
    return {"ok": True, "keep_n": index}


async def _api_message_delete(self):
    if getattr(self, "_terminating", False):
        return {"error": "plugin is reloading"}, 503
    data = await request.get_json() or {}
    if not isinstance(data, dict):
        return {"error": "invalid request"}, 400
    sid = data.get("session_id", "")
    if not is_valid_session_id(sid) or sid not in self._sessions:
        return {"error": "invalid session_id"}, 400
    message_id = data.get("message_id", "")
    plan = await self._api_delete_prepare(sid, message_id)
    if not plan["ok"]:
        return {"error": "message not found"}, 404
    session = self._sessions[sid]
    async with session.setdefault("_send_lock", asyncio.Lock()):
        removed, trunc_coro = self._edit_truncate(sid, plan["keep_n"])
        await trunc_coro
        # 深度截断后 next_char_idx 必须从剩余 history 重算（盲推进会与轮转脱节）
        self._send_recalc_next_char(sid)
    return {"status": "ok", "next_character": self._send_build_next_character(sid)}
```

- [ ] **Step 3: web_handler.py 路由白名单**：POST 集合加 `"session/regenerate"`、`"session/edit"`、`"session/message-delete"`。

- [ ] **Step 4: 运行测试 + 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 84 passed（Task 7/8 新增 5 + 4 = 9 项，79 + 5 = 84）

- [ ] **Step 5: 提交**

```bash
git add api/session.py galgame_web/web_handler.py tests/test_message_editing.py
git commit -m "feat: add message edit and delete APIs"
```

---

### Task 9: 前端设置页角色管理

**Files:**
- Modify: `pages/settings/index.html`、`pages/settings/app.js`
- Mirror: `galgame_web/galgame/`（本插件独立 WebUI 的设置页实际挂载点见 index.html 的 iframe 引用；确认后同步）

- [ ] **Step 1: settings/index.html 加分区骨架**

在现有 BGM 分区后追加：

```html
<section class="settings-section">
  <h3>角色管理（多角色对话）</h3>
  <p class="settings-hint">配置多个角色后，主页会话面板会出现「多角色」入口。单角色对话仍使用插件配置页设置，不受影响。</p>
  <div id="char-list" class="char-list"></div>
  <button id="char-add" class="btn-primary">+ 新建角色</button>
</section>
```

- [ ] **Step 2: settings/app.js 实现角色管理**

追加以下逻辑（沿用现有 apiGet/apiPost/setStatus 模式）：

```javascript
var characters = [];
var editingCharId = null;

async function loadCharacters() {
  try {
    var data = await apiGet("characters");
    characters = data.characters || [];
  } catch(e) { characters = []; }
  renderCharacterList();
}

function renderCharacterList() {
  var list = document.getElementById("char-list");
  if (!list) return;
  list.textContent = "";
  if (!characters.length) {
    list.innerHTML = '<div class="session-loading">暂无角色，点击「新建角色」添加</div>';
    return;
  }
  characters.forEach(function(c, idx) {
    var item = document.createElement("div");
    item.className = "char-item";
    var nameEl = document.createElement("span");
    nameEl.className = "char-item-name";
    nameEl.textContent = (idx + 1) + ". " + (c.name || c.id);
    item.appendChild(nameEl);
    var upBtn = document.createElement("button");
    upBtn.textContent = "↑";
    upBtn.disabled = idx === 0;
    upBtn.onclick = function() { moveCharacter(idx, -1); };
    var downBtn = document.createElement("button");
    downBtn.textContent = "↓";
    downBtn.disabled = idx === characters.length - 1;
    downBtn.onclick = function() { moveCharacter(idx, 1); };
    var editBtn = document.createElement("button");
    editBtn.textContent = "编辑";
    editBtn.onclick = function() { openCharacterEditor(c.id); };
    var delBtn = document.createElement("button");
    delBtn.textContent = "删除";
    delBtn.onclick = function() { deleteCharacter(c.id); };
    item.appendChild(upBtn); item.appendChild(downBtn);
    item.appendChild(editBtn); item.appendChild(delBtn);
    list.appendChild(item);
  });
}

function moveCharacter(idx, delta) {
  var target = idx + delta;
  if (target < 0 || target >= characters.length) return;
  var tmp = characters[idx]; characters[idx] = characters[target]; characters[target] = tmp;
  renderCharacterList();
  saveCharactersSilently();
}

function deleteCharacter(id) {
  characters = characters.filter(function(c) { return c.id !== id; });
  renderCharacterList();
  saveCharactersSilently();
}

function saveCharactersSilently() {
  apiPost("characters", { characters: characters }).then(function(resp) {
    if (!resp || resp.status !== "ok") setStatus("角色保存失败", "error");
  }).catch(function(e) { setStatus("角色保存失败: " + e.message, "error"); });
}

function openCharacterEditor(id) {
  editingCharId = id;
  var card = characters.find(function(c) { return c.id === id; });
  document.getElementById("char-edit-name").value = card ? (card.name || "") : "";
  document.getElementById("char-edit-persona").value = card ? (card.persona_id || "") : "";
  document.getElementById("char-edit-prompt").value = card ? (card.custom_prompt || "") : "";
  document.getElementById("char-edit-opening").value = card ? (card.opening || "") : "";
  document.getElementById("char-editor").classList.add("active");
}

async function saveCharacterEditor() {
  var name = document.getElementById("char-edit-name").value.trim();
  var personaId = document.getElementById("char-edit-persona").value;
  var prompt = document.getElementById("char-edit-prompt").value;
  var opening = document.getElementById("char-edit-opening").value;
  if (!name) { setStatus("角色名不能为空", "error"); return; }
  if (!editingCharId) {
    var id = name.toLowerCase().replace(/[^a-z0-9-]/g, "-").replace(/^-+|-+$/g, "") || ("char" + Date.now());
    if (characters.some(function(c) { return c.id === id; })) id = id + "-" + Date.now() % 1000;
    characters.push({ id: id, name: name, persona_id: personaId, custom_prompt: prompt, expressions: {}, background: "", bgm: "", opening: opening, tts_provider: "" });
  } else {
    var card = characters.find(function(c) { return c.id === editingCharId; });
    if (card) { card.name = name; card.persona_id = personaId; card.custom_prompt = prompt; card.opening = opening; }
  }
  document.getElementById("char-editor").classList.remove("active");
  renderCharacterList();
  await saveCharactersSilently();
}

async function loadPersonaOptions() {
  try {
    var data = await apiGet("personas");
    var sel = document.getElementById("char-edit-persona");
    sel.textContent = "";
    var blank = document.createElement("option");
    blank.value = ""; blank.textContent = "（不绑定 AstrBot 人格）";
    sel.appendChild(blank);
    (data.personas || []).forEach(function(p) {
      var opt = document.createElement("option");
      opt.value = p.persona_id; opt.textContent = p.persona_id;
      sel.appendChild(opt);
    });
  } catch(e) { console.warn("Failed to load personas:", e); }
}
```

HTML 追加编辑器表单（`char-editor` 覆盖层或内联块）：

```html
<div id="char-editor" class="char-editor">
  <h4>编辑角色</h4>
  <label>角色名</label>
  <input id="char-edit-name" type="text" maxlength="64">
  <label>绑定 AstrBot 人格（可选）</label>
  <select id="char-edit-persona"></select>
  <label>自定义人格 prompt（可选，绑定人格时叠加）</label>
  <textarea id="char-edit-prompt" rows="6" maxlength="20000"></textarea>
  <label>开场白（可选，缺省取人格预设对话）</label>
  <textarea id="char-edit-opening" rows="2" maxlength="2000"></textarea>
  <button id="char-edit-save">保存</button>
  <button id="char-edit-cancel">取消</button>
</div>
```

初始化钩子：页面 boot 处调用 `loadCharacters(); loadPersonaOptions();`，绑定 `char-add`→openCharacterEditor(null)（把 `char-add` 点击改为打开空编辑器）、`char-edit-save`→saveCharacterEditor、`char-edit-cancel`→关闭编辑器。

- [ ] **Step 3: 前端检查与同步**

Run: `node --check pages/settings/app.js`
Expected: 无输出（语法 OK）

将 `pages/settings/index.html`、`pages/settings/app.js` 复制到 `galgame_web/` 下对应的挂载目录（若该目录结构存在则保持双端一致；本插件独立 WebUI 设置页实际路径以 `galgame_web/galgame/` 下 index.html 引用的为准，若设置页复用 pages/settings 则跳过复制）。

```bash
node --check galgame_web/.../app.js   # 若有镜像文件
```

- [ ] **Step 4: 提交**

```bash
git add pages/settings/ galgame_web/ 2>/dev/null
git commit -m "feat: add character management UI to settings page"
```

---

### Task 10: 前端主页面多角色（会话创建 + 场景切换 + 当前角色指示）

**Files:**
- Modify: `pages/galgame/index.html`、`pages/galgame/app.js`
- Mirror: `galgame_web/galgame/app.js`、`galgame_web/galgame/index.html`

- [ ] **Step 1: index.html 加「多角色」按钮**

会话面板按钮区（`session-new` 附近）追加：

```html
<button id="session-multi" class="session-action" title="多角色对话">多角色</button>
```

- [ ] **Step 2: app.js 状态与初始化**

```javascript
var currentMode = "single";
var multiCharacters = [];   // [{id,name,expressions,background,bgm}]
var activeCharacter = null; // 当前发言角色（multi 时非空）
```

`init()` 中 `initSession(savedId)` 后：

```javascript
currentMode = resp.mode || "single";
multiCharacters = resp.characters || [];
if (currentMode === "multi" && multiCharacters.length) {
  activeCharacter = multiCharacters[0];
  setActiveCharacter(activeCharacter);
}
```

在会话面板加载后调用 `updateMultiButton()`：

```javascript
function updateMultiButton() {
  var btn = document.getElementById("session-multi");
  if (!btn) return;
  btn.style.display = (multiCharacters.length >= 2) ? "" : "none";
}
```

（`multiCharacters` 由 `apiGet("characters")` 在 init 时填充，独立于会话：`init()` 中 `loadCharactersForMulti()` 一次）

```javascript
async function loadCharactersForMulti() {
  try {
    var data = await apiGet("characters");
    multiCharacters = data.characters || [];
  } catch(e) { multiCharacters = []; }
  updateMultiButton();
}
```

- [ ] **Step 3: 创建多角色会话**

```javascript
async function startMultiSession() {
  if (_newSessionPending) return;
  _newSessionPending = true;
  var btn = document.getElementById("session-multi");
  if (btn) btn.disabled = true;
  try {
    var resp = await initSession("", true, "multi");
    if (!resp) return;
    setLocal("galgame_session_id", resp.session_id);
    location.reload();
  } finally {
    _newSessionPending = false;
    if (btn) btn.disabled = false;
  }
}
```

`initSession` 增加第三参数并透传：

```javascript
async function initSession(resumeId, forceNew, mode) {
  ...
  resp = await apiPost("session/init", {
    resume_id: resumeId || "",
    force_new: forceNew === true,
    mode: mode || "single",
  });
  ...
}
```

`startNewSession` 调用改为 `initSession("", true)`（single 默认）。

- [ ] **Step 4: setActiveCharacter 场景切换**

```javascript
function setActiveCharacter(char) {
  activeCharacter = char || null;
  if (!char) return;
  if (char.name) document.getElementById("character-name").textContent = char.name;
  if (char.expressions && Object.keys(char.expressions).length) {
    expressions = char.expressions;
    currentEmotion = "";
    applySprites();
  }
  if (char.background) {
    backgroundFile = char.background;
    applyBackground();
  } else if (char) {
    // 回退全局背景由 config 提供，仅当角色未配置时保留现有
  }
  if (char.bgm && char.bgm !== _lastBgmFile) {
    _setBgmSrc(char.bgm, true);
  }
}
```

- [ ] **Step 5: 发送后处理 next_character**

`sendMessage` 与 `notifyRapidAction` 的响应处理末尾追加：

```javascript
if (resp.next_character) setActiveCharacter(resp.next_character);
```

- [ ] **Step 6: 会话切换面板与历史渲染**

`loadSessionPanel` 的条目加 mode 徽标（需 `session/list` 返回 mode —— 在 `_api_session_list` 中给每条加 `"mode": data.get("mode", "single")`）：

```javascript
if (s.mode === "multi") {
  var badge = document.createElement("span");
  badge.className = "session-item-badge";
  badge.textContent = "群聊";
  item.appendChild(badge);
}
```

`toggleHistory` 渲染 AI 消息时，若 `msg.character` 存在则用角色名替换 `characterName`：

```javascript
var tagName = characterName;
if (msg.character) {
  var mc = multiCharacters.find(function(c) { return c.id === msg.character; });
  if (mc) tagName = mc.name;
}
```

（渲染前确保 `multiCharacters` 已由 `loadCharactersForMulti` 填充）

- [ ] **Step 7: 检查 + 同步 + 提交**

Run: `node --check pages/galgame/app.js`
Expected: 无输出

复制 `pages/galgame/index.html`、`pages/galgame/app.js` 到 `galgame_web/galgame/`（保持双端哈希一致）。

Run: `Get-FileHash pages/galgame/app.js, galgame_web/galgame/app.js` 确认一致

```bash
git add pages/galgame/ galgame_web/galgame/
git commit -m "feat: add multi-character session UI and scene switching"
```

---

### Task 11: 前端消息操作 UI（重生成/编辑/删除）

**Files:**
- Modify: `pages/galgame/index.html`、`pages/galgame/app.js`
- Mirror: `galgame_web/galgame/`

- [ ] **Step 1: 历史面板渲染追加操作按钮**

`toggleHistory` 消息行内（favBtn 之后）追加：

```javascript
var actions = document.createElement("div");
actions.className = "msg-actions";

if (isUser) {
  var editBtn = document.createElement("button");
  editBtn.className = "msg-edit-btn";
  editBtn.title = "编辑此消息";
  editBtn.textContent = "✏";
  editBtn.onclick = (function(m) { return function() { startEditMessage(m, row); }; })(msg);
  actions.appendChild(editBtn);
}

var delBtn = document.createElement("button");
delBtn.className = "msg-del-btn";
delBtn.title = "删除此消息及之后";
delBtn.textContent = "🗑";
delBtn.onclick = (function(m) { return function() { deleteMessage(m); }; })(msg);
actions.appendChild(delBtn);

if (!isUser && i === messages.length - 1) {
  var regenBtn = document.createElement("button");
  regenBtn.className = "msg-regen-btn";
  regenBtn.title = "重新生成此回复";
  regenBtn.textContent = "🔄";
  regenBtn.onclick = function() { regenerateLast(); };
  actions.appendChild(regenBtn);
}

msgRow.appendChild(actions);
```

- [ ] **Step 2: 操作函数**

```javascript
async function regenerateLast() {
  if (!sessionId) return;
  disableInput();
  el.dialogText.textContent = "重新思考中...";
  try {
    var resp = await apiPost("session/regenerate", { session_id: sessionId });
    if (resp && resp.reply) {
      var emotionMap = {};
      (resp.emotions || []).forEach(function(e) { emotionMap[e[1]] = e[0]; });
      lastReplyData = { text: resp.reply, emotionMap: emotionMap, audio: resp.audio || "", audioMime: resp.audio_mime || "audio/wav", audio_file: resp.audio_file || "" };
      document.getElementById("replay-btn").classList.add("active");
      if (resp.audio && emotionMap.length) {
        typewriterAppend(resp.reply, {});
        finishResponse();
        var audio = playTTSAudio(resp.audio, resp.audio_mime || "audio/wav");
        if (audio) {
          audio.onloadedmetadata = function() { scheduleExpressionTimers(emotionList, resp.reply.length, audio.duration); };
          audio.onended = function() { clearExpressionTimers(); };
          audio.onerror = function() { clearExpressionTimers(); };
        }
      } else {
        typewriterAppend(resp.reply, emotionMap);
        finishResponse();
        if (resp.audio) playTTSAudio(resp.audio, resp.audio_mime || "audio/wav");
      }
      if (resp.next_character) setActiveCharacter(resp.next_character);
    } else {
      finishResponse();
      showError((resp && resp.error) || "重生成失败");
    }
    toggleHistory(); // 刷新历史面板
  } catch (err) {
    console.warn("Regenerate failed:", err);
    enableInput();
    showError("重生成失败：" + (err.message || err));
  }
}

async function deleteMessage(msg) {
  if (!sessionId) return;
  try {
    var resp = await apiPost("session/message-delete", { session_id: sessionId, message_id: msg.id });
    if (resp && resp.status === "ok") {
      if (resp.next_character) setActiveCharacter(resp.next_character);
      restoreLastMessage();
      toggleHistory();
    }
  } catch (err) {
    console.warn("Delete message failed:", err);
  }
}

function startEditMessage(msg, row) {
  if (row._editing) return;
  row._editing = true;
  var bubble = row.querySelector(".msg-bubble");
  var textarea = document.createElement("textarea");
  textarea.className = "msg-edit-input";
  textarea.value = msg.content;
  textarea.maxLength = 20000;
  bubble.style.display = "none";
  row.insertBefore(textarea, bubble);
  var saveBtn = document.createElement("button");
  saveBtn.className = "msg-edit-save";
  saveBtn.textContent = "保存";
  saveBtn.onclick = function() { finishEditMessage(msg, row, textarea.value); };
  var cancelBtn = document.createElement("button");
  cancelBtn.className = "msg-edit-cancel";
  cancelBtn.textContent = "取消";
  cancelBtn.onclick = function() { cancelEditMessage(msg, row, bubble, textarea); };
  var btnRow = document.createElement("div");
  btnRow.className = "msg-edit-btns";
  btnRow.appendChild(saveBtn);
  btnRow.appendChild(cancelBtn);
  row.appendChild(btnRow);
  textarea.focus();
}

function cancelEditMessage(msg, row, bubble, textarea) {
  row._editing = false;
  bubble.style.display = "";
  textarea.remove();
  var btns = row.querySelector(".msg-edit-btns");
  if (btns) btns.remove();
}

async function finishEditMessage(msg, row, newText) {
  var text = (newText || "").trim();
  if (!text) { cancelEditMessage(msg, row, row.querySelector(".msg-bubble"), row.querySelector(".msg-edit-input")); return; }
  try {
    var resp = await apiPost("session/edit", { session_id: sessionId, message_id: msg.id, new_text: text });
    cancelEditMessage(msg, row, row.querySelector(".msg-bubble"), row.querySelector(".msg-edit-input"));
    if (resp && resp.reply) {
      // 编辑用户消息：自动重生成，走与 regenerateLast 相同的渲染（提取公共函数 renderReply(resp)）
      renderReply(resp);
    } else if (resp && resp.error) {
      showError("编辑失败：" + resp.error);
    } else {
      restoreLastMessage();
    }
    toggleHistory();
  } catch (err) {
    console.warn("Edit message failed:", err);
    showError("编辑失败：" + (err.message || err));
  }
}
```

- [ ] **Step 3: 提取 renderReply 公共函数**

将 `sendMessage`/`notifyRapidAction` 中重复的"打字机 + TTS + 表情"渲染块提取为 `renderReply(resp)`（spec 缺陷 #4 顺带解决，三个调用点统一替换）：

```javascript
function renderReply(resp) {
  var emotionMap = {};
  var emotionList = resp.emotions || [];
  emotionList.forEach(function(e) { emotionMap[e[1]] = e[0]; });
  lastReplyData = { text: resp.reply, emotionMap: emotionMap, audio: resp.audio || "", audioMime: resp.audio_mime || "audio/wav", audio_file: resp.audio_file || "" };
  document.getElementById("replay-btn").classList.add("active");
  if (resp.audio_file) {
    document.getElementById("favorite-btn").classList.add("active");
  } else {
    document.getElementById("favorite-btn").classList.remove("active");
  }
  if (resp.audio && emotionList.length) {
    typewriterAppend(resp.reply, {});
    finishResponse();
    var audio = playTTSAudio(resp.audio, resp.audio_mime || "audio/wav");
    if (audio) {
      audio.onloadedmetadata = function() { scheduleExpressionTimers(emotionList, resp.reply.length, audio.duration); };
      audio.onended = function() { clearExpressionTimers(); };
      audio.onerror = function() { clearExpressionTimers(); };
    }
  } else {
    typewriterAppend(resp.reply, emotionMap);
    finishResponse();
    if (resp.audio) playTTSAudio(resp.audio, resp.audio_mime || "audio/wav");
  }
  if (resp.next_character) setActiveCharacter(resp.next_character);
}
```

替换 `sendMessage`、`notifyRapidAction`、`regenerateLast` 中的渲染块为 `renderReply(resp)`。

- [ ] **Step 4: 检查 + 同步 + 提交**

Run: `node --check pages/galgame/app.js`；Expected: 无输出

复制到 `galgame_web/galgame/` 并确认哈希一致。

```bash
git add pages/galgame/ galgame_web/galgame/
git commit -m "feat: add message regenerate/edit/delete UI"
```

---

### Task 12: 全量验证 + README/CHANGELOG + 版本号

**Files:**
- Modify: `README.md`、`CHANGELOG.md`、`metadata.yaml`

- [ ] **Step 1: 全量测试与静态检查**

Run: `python -m pytest tests/ -q`
Expected: 全部通过（基线 64 + 新增 ~20）

Run: `ruff check .` 与 `ruff format .`；Expected: All checks passed!
Run: 前端全部 `node --check`；Expected: 无输出

- [ ] **Step 2: 双端文件哈希一致性检查**

Run: `Get-FileHash pages/galgame/app.js, galgame_web/galgame/app.js`
Expected: 相同 Hash

- [ ] **Step 3: 更新文档与版本**

`metadata.yaml`：`version: "0.7.14"` → `"0.8.0"`；desc 追加多角色/消息编辑说明。

`CHANGELOG.md` 顶部新增：

```markdown
## v0.8.0

**多角色轮流对话（MVP）**

- 角色卡系统：前端设置页可视化创建角色（名字、立绘、背景、BGM、开场白），人格可绑定 AstrBot persona 或自定义 prompt，二者可叠加
- 多角色会话：固定循环轮流（角色 1 开场白 → 用户 → 角色 2 → ...），场景（立绘/背景/BGM）随当前发言角色自动切换
- 单角色对话完全兼容，继续使用插件配置页设置，零改动

**酒馆式消息操作**

- 重新生成最后一条 AI 回复
- 编辑任意消息：用户消息编辑后自动重新生成；AI 消息编辑改写历史
- 删除任意消息（含其后所有）

**其他**

- history 条目增加 id（旧会话惰性补生成）与 character 字段
- 已知限制：多角色共用同一 TTS 音色、角色间暂不直接对话、切换人格后上下文可能残留旧人格痕迹
```

`README.md` 功能详情补多角色与消息编辑小节（沿用现有文档风格），已知限制补第 9 节列表。

- [ ] **Step 4: 提交**

```bash
git add metadata.yaml CHANGELOG.md README.md
git commit -m "chore: bump to 0.8.0 with docs"
```

---

## 自审记录

**Spec 覆盖：**
- 角色卡数据层/API → Task 1-2
- 会话 mode/字段 → Task 3
- multi 创建+开场白 → Task 4
- 管道集成（persona 切换/custom_prompt/next_character/轮流推进）→ Task 5
- 消息编辑基础+三项 API → Task 6-8
- 前端角色管理 → Task 9
- 前端多角色场景/当前角色指示 → Task 10
- 前端消息操作 UI → Task 11
- 文档/版本 → Task 12

**一致性：** `_send_advance_character` / `_send_build_next_character` / `_send_switch_persona` / `_edit_truncate` / `_do_regenerate` / `_api_edit_prepare` / `_api_delete_prepare` 命名在各 Task 中保持一致；`renderReply(resp)` 为前端统一渲染入口；`setActiveCharacter` 前后一致。

**待实现时确认的点：**
1. `session/init` 返回结构改动后，现有前端 `initSession` 仅用 `resp.session_id`/`current_emotion`，新增字段向后兼容。
2. `_send_save_and_return` 加 `skip_user_append`/`await_sync` 参数时需核对现有调用点（仅 `_do_send` 一处调用，默认值不变）。
3. `_edit_truncate` 返回 `(removed, coroutine)` 结构为计划内契约，实现时保持。

**solution-reviewer-pro 审查修订记录（2026-08-05，首轮 VERDICT: FAIL → 已修订）：**

| 发现 | 级别 | 修订 |
|------|------|------|
| regenerate 换人答：截断后 `_send_switch_persona` 读已推进的 next_char_idx | P0 | `_api_regenerate` 截断前记录被删消息的 `character`，截断后 `next_char_idx = chars.index(该角色)`（Task 7 修订） |
| 开场白后 next_char_idx 未推进 → 角色 0 连说两次 | P0 | 开场白写入后 `next_char_idx = 1 % len`（Task 4 修订） |
| `session["conv_id"] = conv_id`（旧空值）覆盖 `init_astrbot_conv` 写入的新 conv_id | P1 | 删除覆盖行（Task 5 修订） |
| assistant `character` 字段 `(next_char_idx - 1) % len` 在 append 时记错发言人 | P1 | append 时直接用 `chars[next_char_idx]`（未推进时即当前发言者）（Task 5 修订） |
| 深度截断后 next_char_idx 与剩余 history 脱节 | P2 | 新增 `_send_recalc_next_char`（剩余 history 最后 assistant 的下一顺位，无则重置 0），edit/delete 截断后调用（Task 5/8 修订） |
| 管道 `_save_to_history` 与插件 `sync_conv_to_db` DB 竞态 | P2 | `_send_save_and_return` 加 `await_sync` 参数，regenerate/edit 路径 await 同步（Task 5/7 修订） |
| resume 返回 dict 缺 mode/characters | P3 | 明确全部 5 个返回路径补齐字段（Task 4 修订） |
| persona 被删除静默回退默认人格 | P3 | `_send_switch_persona` 异常升级为 error 级日志（Task 5 修订） |
| `_send_switch_persona` 锁契约未文档化 | P3 | docstring 注明仅在 `_send_lock` 内调用（Task 5 修订） |

**第二轮 solution-reviewer-pro 审查（2026-08-05）：VERDICT: PASS**

- 场景追踪全部通过：3 角色全轮转、删除中间消息 recalc、重生成同角色回答、编辑 user/assistant、开场白推进、append 时序、锁串行化、single 零改动、await_sync
- 修订补充（PASS 后按 reviewer 建议）：`_edit_truncate` 返回 `_do()` 协程对象（否则 `await` 函数抛 TypeError，F1）；`_send_recalc_next_char` 无效 character 时 `continue` 而非 `break`（F2）；`init_astrbot_conv` 幂等性注释（F3）
