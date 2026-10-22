"""Pipeline-level filler for silent tool turns.

Measured gap: even qwen3.8-27b was silent on 1 of 6 tool turns, Sarvam on 5 of
6. The tool output is not the problem - the model never spoke before calling
the tool. ToolTurnFiller covers that for every provider, and must never talk
over a model that did speak.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.pipeline import ToolTurnFiller, tool_filler_for


class _Session:
    def __init__(self, agent_state: str = "listening") -> None:
        self.agent_state = agent_state
        self.said: list[tuple[str, dict]] = []

    def say(self, text: str, **kwargs) -> None:
        self.said.append((text, kwargs))


def _user(transcript: str = "hello", final: bool = True):
    return SimpleNamespace(transcript=transcript, is_final=final)


def _assistant(text: str):
    return SimpleNamespace(
        item=SimpleNamespace(role="assistant", text_content=text)
    )


def _tool_start(name: str):
    return SimpleNamespace(
        update=SimpleNamespace(
            type="tool_call_started",
            function_call=SimpleNamespace(name=name),
        )
    )


def _make() -> tuple[_Session, ToolTurnFiller]:
    session = _Session()
    return session, ToolTurnFiller(session)


def test_filler_phrases_are_tool_aware() -> None:
    assert tool_filler_for("record_extracted_field") == "Let me note that down."
    assert tool_filler_for("unknown_tool") == "One moment, please."
    assert tool_filler_for("end_call") is None


def test_silent_tool_turn_speaks_one_cue() -> None:
    session, filler = _make()
    filler.on_user_input_transcribed(_user())
    filler.on_conversation_item_added(_assistant(""))
    filler.on_tool_execution_updated(_tool_start("record_extracted_field"))

    assert len(session.said) == 1
    text, kwargs = session.said[0]
    assert text == "Let me note that down."
    # A filler is not a turn: the model must not see it in its own history.
    assert kwargs["add_to_chat_ctx"] is False
    assert kwargs["allow_interruptions"] is True


def test_no_filler_when_the_model_already_spoke() -> None:
    session, filler = _make()
    filler.on_user_input_transcribed(_user())
    # A single assistant message may contain spoken text AND tool calls.
    filler.on_conversation_item_added(_assistant("I've noted that."))
    filler.on_tool_execution_updated(_tool_start("record_extracted_field"))

    assert session.said == []


def test_one_filler_per_turn() -> None:
    session, filler = _make()
    filler.on_user_input_transcribed(_user())
    filler.on_tool_execution_updated(_tool_start("record_extracted_field"))
    filler.on_tool_execution_updated(_tool_start("record_extracted_field"))

    assert len(session.said) == 1


def test_new_user_turn_rearms_the_filler() -> None:
    session, filler = _make()
    filler.on_user_input_transcribed(_user())
    filler.on_tool_execution_updated(_tool_start("record_extracted_field"))
    filler.on_user_input_transcribed(_user("next answer"))
    filler.on_tool_execution_updated(_tool_start("record_extracted_field"))

    assert len(session.said) == 2


def test_partial_transcript_does_not_reset_mid_turn() -> None:
    session, filler = _make()
    filler.on_user_input_transcribed(_user("fever", final=True))
    filler.on_tool_execution_updated(_tool_start("record_extracted_field"))
    # A late partial belongs to the same caller turn; it must not re-arm and
    # produce a second cue for the same tool batch.
    filler.on_user_input_transcribed(_user("fever and", final=False))
    filler.on_tool_execution_updated(_tool_start("record_extracted_field"))

    assert len(session.said) == 1


def test_filler_does_not_stack_over_speaking_audio() -> None:
    session = _Session(agent_state="speaking")
    filler = ToolTurnFiller(session)
    filler.on_user_input_transcribed(_user())
    filler.on_tool_execution_updated(_tool_start("record_extracted_field"))

    assert session.said == []


def test_end_call_is_exempt() -> None:
    session, filler = _make()
    filler.on_user_input_transcribed(_user())
    filler.on_tool_execution_updated(_tool_start("end_call"))

    assert session.said == []
