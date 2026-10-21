"""WebChat payload contract: reasoning must stay out unless opted in.

AstrBot 4.29+ defaults ``enable_reasoning`` to True for WebChat requests and
prepends "\U0001f914 \u601d\u8003: ..." to the reply chain in the
result_decorate stage. The galgame plugin collects that chain verbatim, so the
flag has to be sent explicitly or the reasoning text leaks into the reply, the
plugin TTS and both history stores.
"""

import asyncio
import importlib
from pathlib import Path

PACKAGE_NAME = Path(__file__).resolve().parents[1].name
pipeline_module = importlib.import_module(f"{PACKAGE_NAME}.galgame_web.pipeline")


class _FakeChatQueue:
    def __init__(self):
        self.items = []

    async def put(self, item):
        self.items.append(item)


class _FakeBackQueue:
    async def get(self):
        # End the consumer immediately: the real pipeline waits up to 300 s for
        # an "end" message, and a fake that never answers would stall the suite.
        return {"type": "end", "data": ""}


class _FakeQueueManager:
    def __init__(self):
        self.chat_queue = _FakeChatQueue()
        self.removed = []

    def get_or_create_back_queue(self, msg_id, wc_sid):
        return _FakeBackQueue()

    def get_or_create_queue(self, session_id):
        return self.chat_queue

    def remove_back_queue(self, msg_id):
        self.removed.append(msg_id)


def _push(monkeypatch, config):
    fake = _FakeQueueManager()
    monkeypatch.setattr(pipeline_module, "webchat_queue_mgr", fake)
    result = asyncio.run(
        pipeline_module.push_through_pipeline(config, "tester", "sid-1", "hello")
    )
    assert len(fake.chat_queue.items) == 1
    username, session_id, payload = fake.chat_queue.items[0]
    return result, fake, username, session_id, payload


def test_payload_disables_reasoning_and_streaming_by_default(monkeypatch):
    result, fake, username, session_id, payload = _push(monkeypatch, {})
    assert username == "tester"
    assert session_id == "sid-1"
    assert payload["enable_streaming"] is False
    assert payload["enable_reasoning"] is False
    assert payload["flags"] == {"enable_streaming": False, "enable_reasoning": False}
    assert payload["message"] == [{"type": "plain", "text": "hello"}]
    assert payload["selected_model"] is None
    assert payload["selected_provider"] is None
    assert result["text"] == ""
    assert fake.removed == [payload["message_id"]]


def test_payload_keeps_selected_provider_trimmed(monkeypatch):
    _, _, _, _, payload = _push(monkeypatch, {"llm_provider": "  openai/gpt-4o-mini  "})
    assert payload["selected_provider"] == "openai/gpt-4o-mini"
    assert payload["enable_reasoning"] is False


def test_payload_honours_explicit_show_reasoning_opt_in(monkeypatch):
    _, _, _, _, payload = _push(monkeypatch, {"show_reasoning": True})
    assert payload["enable_reasoning"] is True
    assert payload["flags"] == {"enable_streaming": False, "enable_reasoning": True}


def test_payload_treats_non_boolean_show_reasoning_as_disabled(monkeypatch):
    _, _, _, _, payload = _push(monkeypatch, {"show_reasoning": "false"})
    assert payload["enable_reasoning"] is False
