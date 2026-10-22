"""Turn latency must report what the caller experiences (call 18 regression).

A live call reported ``llm_first_token_ms=19899 / e2e=20158`` for a turn whose
audio started 580 ms after the caller stopped speaking: the item-commit time
was used as a first-token proxy and ``e2e`` summed three stage timings that
streaming had already overlapped. Worse, the stall watchdog keyed on the same
commit time, so it called those slow-but-live turns dead and spoke "Sorry, I
didn't quite catch that" over the answer.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

from app.pipeline import FallbackLLM, TurnTelemetry


class FakeBackend:
    def __init__(self) -> None:
        self.rows: list[list[dict[str, Any]]] = []

    async def post_turns(self, call_id, turns):  # noqa: ANN001
        self.rows.append(list(turns))
        return True


def _telemetry(**kwargs: Any) -> TurnTelemetry:
    return TurnTelemetry(
        session=SimpleNamespace(),
        backend=FakeBackend(),
        call_id="18",
        **kwargs,
    )


def test_e2e_is_the_silence_the_caller_actually_heard() -> None:
    backend = FakeBackend()
    tele = TurnTelemetry(
        session=SimpleNamespace(), backend=backend, call_id="18"
    )
    tele._user_text = "lekunnaru"
    tele._agent_text = "sure, noted"
    tele._end_of_speech_at = time.monotonic() - 0.75
    tele._stt_final_ms = 400.0
    tele._llm_first_token_ms = 300.0
    tele._tts_first_audio_ms = 180.0
    tele._on_agent_state_changed(
        SimpleNamespace(old_state="thinking", new_state="speaking")
    )

    asyncio.run(tele.flush_pending())

    agent_row = [r for r in backend.rows[0] if r["speaker"] == "agent"][0]
    # 750 ms of real heard silence, NOT the 400+300+180 sum the old formula
    # posted for the same turn.
    assert 700 <= agent_row["e2e_ms"] <= 900, agent_row["e2e_ms"]
    assert agent_row["e2e_ms"] != 880.0  # the overlapped sum, for contrast


def test_agent_speaking_before_the_caller_finished_is_not_a_latency() -> None:
    backend = FakeBackend()
    tele = TurnTelemetry(
        session=SimpleNamespace(), backend=backend, call_id="18"
    )
    tele._user_text = "hi"
    tele._agent_text = "mm-hmm"
    tele._end_of_speech_at = time.monotonic()
    tele._first_speech_at = time.monotonic() - 2.0  # barge-in cue
    tele._stt_final_ms = 300.0
    tele._llm_first_token_ms = 200.0
    tele._tts_first_audio_ms = 150.0

    asyncio.run(tele.flush_pending())

    # Negative gap is meaningless, so it falls back to the stage sum instead
    # of posting a latency the caller never experienced.
    assert backend.rows[0][-1]["e2e_ms"] == 650.0


def test_generation_length_is_never_reported_as_first_token() -> None:
    tele = _telemetry()
    tele._reply_start_at = time.monotonic() - 19.9

    tele._on_conversation_item_added(
        SimpleNamespace(
            item=SimpleNamespace(
                type="message", role="assistant", text_content="a long reply"
            )
        )
    )

    assert tele._llm_first_token_ms is None
    assert tele._llm_reply_ms is not None and tele._llm_reply_ms > 19000


def test_watchdog_only_calls_a_turn_dead_when_nothing_is_coming() -> None:
    tele = _telemetry()
    assert tele._watchdog_is_dead() is True

    alive = _telemetry(llm=SimpleNamespace(first_token_ms=420.0))
    assert alive._watchdog_is_dead() is False

    spoken = _telemetry()
    spoken._on_agent_state_changed(
        SimpleNamespace(old_state="thinking", new_state="speaking")
    )
    assert spoken._watchdog_is_dead() is False

    committed = _telemetry()
    committed._got_agent_item = True
    committed._agent_text = "done"
    assert committed._watchdog_is_dead() is False


def test_llm_chain_latches_the_first_content_token_of_an_exchange() -> None:
    llm = FallbackLLM([SimpleNamespace(model="m")])
    assert llm.first_token_ms is None

    llm._note_first_content(900.0)
    llm._note_first_content(640.0)  # a later member answered faster
    assert llm.first_token_ms == 640.0

    llm.begin_exchange()
    assert llm.first_token_ms is None
