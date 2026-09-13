"""Tool-call leak into speech/transcript: scrubber (B).

When the LLM emitted tool-call markup as inline assistant TEXT (instead of a
structured tool call), that markup got spoken and saved. We scrub the markup
before it reaches captions, _agent_text, and the backend flush, and skip
non-message conversation items entirely.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.pipeline import TurnTelemetry
from app.prompting import scrub_speech_text


def test_tool_call_block_scrubbed() -> None:
    out = scrub_speech_text(
        "I will check that for you <tool_call>record_extracted_field(field_name='a')</tool_call> please hold."
    )
    assert "<tool_call>" not in out
    assert "please hold" in out


def test_function_markup_scrubbed() -> None:
    out = scrub_speech_text("Calling <function=end_call> summary")
    assert "<function=" not in out


def test_parameter_markup_scrubbed() -> None:
    out = scrub_speech_text("value <parameter=reason> now")
    assert "<parameter=" not in out


def test_openai_tool_calls_json_scrubbed() -> None:
    out = scrub_speech_text('here {"tool_calls": [{"function": {"name": "end_call"}}]} done')
    assert "tool_calls" not in out.lower()
    assert "done" in out


def test_plain_text_untouched() -> None:
    original = "Good morning, is this Alex Johnson?"
    assert scrub_speech_text(original) == original


class _FakeSession:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def on(self, name: str):
        def _register(fn: Any) -> Any:
            self.handlers[name] = fn
            return fn

        return _register


def test_tool_markup_scrubbed_before_flush(fake_backend: Any) -> None:
    session = _FakeSession()
    telemetry = TurnTelemetry(
        session=session,  # type: ignore[arg-type]
        backend=fake_backend,
        call_id="c1",
        room=None,
    )
    telemetry.attach()

    session.handlers["user_input_transcribed"](
        type("Ev", (), {"transcript": "yes it is", "is_final": True})()
    )
    item = type(
        "Item", (), {"role": "assistant",
                      "text_content": "Sure <tool_call><function=end_call></tool_call> goodbye"}
    )()
    session.handlers["conversation_item_added"](type("Ev", (), {"item": item})())

    asyncio.run(telemetry.flush_pending())

    _, turns = fake_backend.turn_posts[0]
    agent = [t for t in turns if t["speaker"] == "agent"][0]
    assert "<tool_call>" not in agent["text"]
    assert "<function=" not in agent["text"]
    assert "goodbye" in agent["text"]


def test_tool_call_item_skipped_from_agent_text(fake_backend: Any) -> None:
    session = _FakeSession()
    telemetry = TurnTelemetry(
        session=session,  # type: ignore[arg-type]
        backend=fake_backend,
        call_id="c1",
        room=None,
    )
    telemetry.attach()

    # A structured function-call item (not a message) must not enter agent text.
    item = type("Item", (), {"role": "assistant", "type": "tool_call", "text_content": "n/a"})()
    session.handlers["conversation_item_added"](type("Ev", (), {"item": item})())

    assert telemetry._agent_text == ""
