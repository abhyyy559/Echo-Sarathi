"""Text that reaches phone TTS must be pronounceable, or synthesis 400s.

Call 20 lost ~6.6 s mid-reply because qwen put a bare "..." and then a Han
character into Telugu sentences; Sarvam rejected both segments and the agent
framework re-sent each one several times.
"""

from types import SimpleNamespace

from app.pipeline import _chunk_has_content, _speak_chunk_content
from app.prompting import speakable_text


def test_punctuation_only_reply_is_not_spoken():
    assert speakable_text("...") == ""
    assert speakable_text("—") == ""
    assert speakable_text(" ") == ""


def test_foreign_script_leak_is_dropped_not_the_sentence():
    assert speakable_text("రెండు రోజుల అవసరం అ明白ంది.") == "రెండు రోజుల అవసరం అంది."
    assert speakable_text("会議 tomorrow") == " tomorrow"


def test_spacing_survives_so_words_do_not_glue_together():
    assert speakable_text(" fever ") == " fever "
    assert speakable_text("fever వల్ల") == "fever వల్ల"


def _chunk(content=None, tool_calls=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(delta=None, choices=[SimpleNamespace(delta=delta)]), delta


def test_streamed_delta_is_rewritten_in_place():
    chunk, delta = _chunk(content="...")
    _speak_chunk_content(chunk)
    assert delta.content == ""
    # A delta that carries no speech must not count as content, otherwise the
    # turn is recorded (and measured) as if the caller had been answered.
    assert not _chunk_has_content(chunk)


def test_tool_call_delta_is_left_alone():
    chunk, delta = _chunk(content=None, tool_calls=[{"id": "1"}])
    _speak_chunk_content(chunk)
    assert delta.tool_calls == [{"id": "1"}]
    assert _chunk_has_content(chunk)
