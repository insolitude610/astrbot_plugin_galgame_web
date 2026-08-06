import asyncio
import importlib
import pathlib
import uuid

PACKAGE_NAME = pathlib.Path(__file__).resolve().parents[1].name
_session_api = importlib.import_module(f"{PACKAGE_NAME}.api.session")
SessionAPI = _session_api.SessionAPI


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
    return {
        "umo": f"webchat:FriendMessage:webchat!astrbot!{_sid()}",
        "conv_id": "c1",
        "history": history,
        "current_emotion": "neutral",
        "created_at": 1,
        "_lock": asyncio.Lock(),
        "mode": "single",
    }


def _make_api(history):
    api = SessionAPI()
    api._sessions = {"s" * 32: _session(history)}
    api.context = _FakeCtx()
    return api


def test_find_message_index():
    api = _make_api(
        [
            {"id": "a", "role": "user", "content": "x"},
            {"id": "b", "role": "assistant", "content": "y"},
        ]
    )
    assert api._edit_find_index("s" * 32, "b") == 1
    assert api._edit_find_index("s" * 32, "zzz") is None


def test_truncate_history():
    api = _make_api(
        [
            {"id": "a", "role": "user", "content": "x"},
            {"id": "b", "role": "assistant", "content": "y"},
            {"id": "c", "role": "user", "content": "z"},
        ]
    )
    removed, trunc_coro = api._edit_truncate("s" * 32, 1)
    asyncio.run(trunc_coro)
    assert removed == [
        {"id": "b", "role": "assistant", "content": "y"},
        {"id": "c", "role": "user", "content": "z"},
    ]
    assert api._sessions["s" * 32]["history"] == [
        {"id": "a", "role": "user", "content": "x"}
    ]
