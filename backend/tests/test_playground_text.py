"""Playground TEXT-mode tests: POST /api/playground/sessions/{call_id}/turns.

Covers (with the Groq HTTP client monkeypatched — no network):
- happy path: user turn -> reply, both persisted as Transcript rows
- event=start opening utterance without a user message
- tool-call path: record_extracted_field inserts ExtractedField rows and the
  follow-up request carries the tool result
- end_call tool completes the call with a summary
- 503 when GROQ_API_KEY is unset
- org isolation: another tenant's call id is 404
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.routers.playground as playground_module
from conftest import auth_headers, make_settings, register
from test_agents import version_payload
from test_playground import _make_agent_and_version


# --- httpx fakes ---------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.status_code = 200

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient inside app.routers.playground."""

    scripted: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    async def post(self, url: str, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> _FakeResponse:
        _FakeAsyncClient.requests.append({"url": url, "json": json, "headers": headers})
        assert _FakeAsyncClient.scripted, "no scripted Groq response left"
        return _FakeResponse(_FakeAsyncClient.scripted.pop(0))


@pytest.fixture()
def groq_client(session_factory, monkeypatch):  # type: ignore[no-untyped-def]
    """App client with GROQ_API_KEY set and httpx patched out."""
    monkeypatch.setattr(playground_module.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.scripted = []
    _FakeAsyncClient.requests = []
    fresh = create_groq_app(session_factory)
    with TestClient(fresh) as test_client:
        yield test_client
    _FakeAsyncClient.scripted = []
    _FakeAsyncClient.requests = []


def create_groq_app(session_factory: Any):  # type: ignore[no-untyped-def]
    from app.main import create_app

    fresh = create_app(make_settings(groq_api_key="test-groq-key"))
    fresh.state.session_factory = session_factory
    return fresh


def script(*messages: dict[str, Any]) -> None:
    """Queue chat-completion payloads; each payload is a full API response body."""
    for message in messages:
        _FakeAsyncClient.scripted.append({"choices": [{"message": message}]})
    _FakeAsyncClient.requests = []


def chat(content: str) -> dict[str, Any]:
    return {"role": "assistant", "content": content}


def tool_call(name: str, arguments: dict[str, Any], call_id: str = "call_1") -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


def start_session(client: TestClient, token: str) -> int:
    ids = _make_agent_and_version(client, token)
    session = client.post(
        "/api/playground/sessions",
        json={"agent_version_id": ids["version"]["id"]},
        headers=auth_headers(token),
    )
    assert session.status_code == 200, session.text
    return int(session.json()["call_id"])


@pytest.fixture(autouse=True)
def offline_livekit(monkeypatch):
    """Session setup must not contact even a local LiveKit server."""
    async def update_room_metadata(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "livekit.api.room_service.RoomService.update_room_metadata",
        update_room_metadata,
    )


def start_language_session(client, token, language, disclosure):
    """A non-college session created entirely through the public HTTP API."""
    agent = client.post(
        "/api/agents",
        json={"name": "Sahithi", "description": "Site visit follow-up"},
        headers=auth_headers(token),
    )
    assert agent.status_code == 201, agent.text
    version = client.post(
        f"/api/agents/{agent.json()['id']}/versions",
        json=version_payload(
            system_prompt="Confirm the site visit; collect the preferred time.",
            company_context={"company_name": "Skyline Estates", "visit_hours": "10 AM to 5 PM"},
            disclosure_script=disclosure,
            question_flow=[{"step": 1, "question": "What time works for your site visit?"}],
            extraction_schema={
                "preferred_time": {
                    "type": "string", "description": "Preferred visit time", "validation": "required",
                    "confidence_threshold": 0.7,
                },
            },
            voice_settings={"voice_id": "demo-voice", "speed": 1.0, "language": language},
        ),
        headers=auth_headers(token),
    )
    assert version.status_code == 201, version.text
    session = client.post(
        "/api/playground/sessions",
        json={"agent_version_id": version.json()["id"], "contact": {"contact_name": "Kiran"}},
        headers=auth_headers(token),
    )
    assert session.status_code == 200, session.text
    return int(session.json()["call_id"])


# --- tests ---------------------------------------------------------------------


def test_first_telugu_turn_instructs_default_tenglish_after_verbatim_disclosure(groq_client):
    """Inspect the model request, not the fake reply's linguistic quality."""
    token, _ = register(groq_client)
    disclosure = "నమస్కారం, ఇది Skyline Estates నుండి ఆటోమేటెడ్ కాల్."
    call_id = start_language_session(groq_client, token, "te", disclosure)
    script(chat("సరే అండి."))
    response = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "అవునండి, నేనే మాట్లాడుతున్నాను"},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    prompt = _FakeAsyncClient.requests[0]["json"]["messages"][0]["content"]
    assert f"word-for-word:\n{disclosure}" in prompt
    for instruction in (
        "Default to Tenglish",
        "everyday spoken Telugu syntax with familiar English terms",
        "even if the caller uses only Telugu",
        "Telugu script for Telugu and English spelling for English",
        "not full/formal or bookish Telugu",
        "No English word quota; do not translate every word",
        "Never translate verbatim disclosures or proper names",
        "Examples are style only, not facts or mission",
        "రేపటి site visit‌కి వస్తున్నారా అండి, లేక reschedule చేయాలా?",
        "After the verbatim disclosure, default generated replies to Tenglish",
    ):
        assert instruction in prompt
    assert "start in the disclosure's language" not in prompt
    assert "Confirm the site visit; collect the preferred time." in prompt
    assert '"visit_hours": "10 AM to 5 PM"' in prompt


@pytest.mark.parametrize("language", ["te", "en", "hi"])
def test_language_policy_survives_compaction_and_caller_switches(groq_client, language):
    """The HTTP-model boundary carries policy through first and compact turns."""
    token, _ = register(groq_client)
    # An English disclosure must stay verbatim, not set Telugu reply style.
    disclosure = "This is Sahithi, an AI assistant from Skyline Estates."
    call_id = start_language_session(groq_client, token, language, disclosure)
    response = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"event": "start"}, headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["reply_text"].startswith(disclosure)
    assert _FakeAsyncClient.requests == []

    caller_turns = (
        "అవునండి, నేనే మాట్లాడుతున్నాను",
        "Please speak in English.",
        "Where is the property located?",
        "సరే అండి, ఎక్కడికి రావాలి?",
    )
    for index, caller_text in enumerate(caller_turns):
        script(chat("సరే అండి."))
        response = groq_client.post(
            f"/api/playground/sessions/{call_id}/turns",
            json={"text": caller_text}, headers=auth_headers(token),
        )
        assert response.status_code == 200, response.text
        assert response.json()["done"] is False
        messages = _FakeAsyncClient.requests[0]["json"]["messages"]
        prompt = messages[0]["content"]
        assert messages[-1] == {"role": "user", "content": caller_text}
        if index >= 2:
            assert any(m.get("content") == "Please speak in English." for m in messages)
        if index < 2:
            assert f"word-for-word:\n{disclosure}" in prompt
            assert "never stack two questions" in prompt
            assert "NEVER ask for something the caller just told you" in prompt
            assert "Say goodbye ONCE" in prompt and "end_call(summary)" in prompt
        else:
            assert "MANDATORY DISCLOSURE" not in prompt
            assert "Still needed: preferred_time" in prompt
            assert "one thing per reply" in prompt
            assert "never ask for something they already answered" in prompt
            assert "finish with end_call(summary)" in prompt

        if language == "te":
            for instruction in (
                "Default to Tenglish",
                "even if the caller uses only Telugu",
                "Telugu script for Telugu and English spelling for English",
                "No English word quota; do not translate every word",
                "Never translate verbatim disclosures or proper names",
                "Honor requested English fully; stay in English while the caller continues",
                "return naturally on Telugu/Tenglish, never automatically after one turn",
                "Answer questions directly from known facts, then ask the next missing fact",
            ):
                assert instruction in prompt
            if index < 2:
                assert "You cannot send messages" in prompt
                assert "Never say you did any of those" in prompt
            else:
                assert "Never claim WhatsApp sent or coordinator notified" in prompt
                assert "Examples are style only, not facts or mission" in prompt
        else:
            assert "Tenglish" not in prompt
            assert "site visit‌కి" not in prompt
            assert "Telugu script" not in prompt
            if index < 2:
                assert (
                    "- Match the caller's language: start in the disclosure's language, "
                    "and if they speak another one or mix languages, follow them rather "
                    "than insisting on yours.\n"
                ) in prompt
            elif language == "hi":
                assert "Speak Hindi, using the caller's own English words as they do.\n" in prompt


@pytest.mark.parametrize(
    "language,disclosure,intro,greeting",
    [
        (
            "te", "నమస్కారం, ఇది {identity}Skyline Estates నుండి ఆటోమేటెడ్ కాల్.",
            "Hi Kiran గారు, నేను Sahithi. Kiran గారు మాట్లాడుతున్నారా?",
            "Hi Kiran గారు. Kiran గారు మాట్లాడుతున్నారా?",
        ),
        (
            "en", "Hello, this is {identity}an automated call from Skyline Estates.",
            "Hi Kiran, Sahithi here. Am I speaking with Kiran?",
            "Hi Kiran. Am I speaking with Kiran?",
        ),
        (
            "hi", "नमस्ते, यह {identity}Skyline Estates से एक स्वचालित कॉल है।",
            "नमस्ते Kiran जी, मैं Sahithi बोल रही हूँ। क्या मैं Kiran जी से बात कर रही हूँ?",
            "नमस्ते Kiran जी। क्या मैं Kiran जी से बात कर रही हूँ?",
        ),
    ],
    ids=["te", "en", "hi"],
)
@pytest.mark.parametrize("identity_in_disclosure", [False, True])
def test_generated_opening_preserves_disclosure_and_language(
    groq_client, language, disclosure, intro, greeting, identity_in_disclosure,
):
    token, _ = register(groq_client)
    disclosure = disclosure.format(identity="Sahithi, " if identity_in_disclosure else "")
    call_id = start_language_session(groq_client, token, language, disclosure)
    response = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"event": "start"}, headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reply_text"].startswith(disclosure + " ")
    assert body["reply_text"] == disclosure + " " + (greeting if identity_in_disclosure else intro)
    assert body["reply_text"].count("?") == 1
    assert body["done"] is False
    assert body["turn_index"] == 0
    assert _FakeAsyncClient.requests == []


@pytest.mark.parametrize(
    "language,expected",
    [
        ("te", "Sorry, అర్థం కాలేదు - మళ్లీ చెప్పండి?"),
        ("en", "Sorry, I didn't catch that - could you say that again?"),
        ("hi", "क्षमा कीजिए, समझ नहीं आया - फिर से बता सकते हैं?"),
    ],
    ids=["te", "en", "hi"],
)
def test_generated_retry_after_empty_model_reply(groq_client, language, expected):
    token, _ = register(groq_client)
    call_id = start_language_session(groq_client, token, language, "This is an automated call.")
    script(chat(""))
    response = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "ఏమో అండి"}, headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["reply_text"] == expected
    assert response.json()["reply_text"].count("?") == 1
    assert response.json()["done"] is False
    assert response.json()["extracted_fields"] == []
    assert not _FakeAsyncClient.scripted


@pytest.mark.parametrize(
    "language,expected",
    [("te", "సరే, Thanks."), ("en", "Got it, thank you."), ("hi", "ठीक है, धन्यवाद।")],
    ids=["te", "en", "hi"],
)
def test_generated_ack_does_not_reask_a_recorded_answer(groq_client, language, expected):
    token, _ = register(groq_client)
    call_id = start_language_session(groq_client, token, language, "This is an automated call.")
    script(
        tool_call("record_extracted_field", {
            "field_name": "preferred_time", "value": "evening", "confidence": 0.9,
        }),
        chat(""),
    )
    response = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "evening"}, headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["reply_text"] == expected
    assert "?" not in response.json()["reply_text"]
    assert response.json()["done"] is False
    assert response.json()["extracted_fields"] == [
        {"field_name": "preferred_time", "field_value": "evening", "confidence": 0.9},
    ]
    assert not _FakeAsyncClient.scripted


@pytest.mark.parametrize(
    "language,expected",
    [
        ("te", "సరే, Thanks అండి. బై."),
        ("en", "Thank you for your time. Goodbye."),
        ("hi", "आपके समय के लिए धन्यवाद। नमस्ते।"),
    ],
    ids=["te", "en", "hi"],
)
def test_generated_goodbye_ends_once_after_silent_end_call(groq_client, language, expected):
    token, _ = register(groq_client)
    call_id = start_language_session(groq_client, token, language, "This is an automated call.")
    script(tool_call("end_call", {"summary": "Caller wants to stop."}), chat(""))
    response = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "No, that's all. Goodbye."}, headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["reply_text"] == expected
    assert "?" not in response.json()["reply_text"]
    assert response.json()["done"] is True
    assert not _FakeAsyncClient.scripted
    request_count = len(_FakeAsyncClient.requests)
    further = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "hello again"}, headers=auth_headers(token),
    )
    assert further.status_code == 409
    assert len(_FakeAsyncClient.requests) == request_count
    completed = groq_client.post(
        f"/api/playground/sessions/{call_id}/complete", headers=auth_headers(token),
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert completed.json()["summary"] == "Caller wants to stop."
    assert [
        row["text"] for row in completed.json()["transcript"] if row["speaker"] == "agent"
    ] == [expected]


def test_turn_happy_path_persists_caller_and_agent_rows(groq_client, session_factory):
    from app.models import Transcript

    token, _ = register(groq_client)
    call_id = start_session(groq_client, token)

    script(chat("Sorry to hear that. How long has he been unwell?"))
    resp = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "My son was absent because he had a fever."},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reply_text"] == "Sorry to hear that. How long has he been unwell?"
    assert body["done"] is False
    # The caller's plain-spoken reason is backfilled ("fever" answers
    # reason_for_absence via the synonym escape hatch).
    assert body["extracted_fields"] == [
        {
            "field_name": "reason_for_absence",
            "field_value": "My son was absent because he had a fever",
            "confidence": 0.7,
        }
    ]
    assert body["turn_index"] == 1  # caller row at 0, agent row at 1

    # The Groq request carries the slim system prompt + history + the new turn.
    sent = _FakeAsyncClient.requests[-1]["json"]
    system_msg = sent["messages"][0]["content"]
    assert "MANDATORY DISCLOSURE" in system_msg
    assert sent["model"] == "qwen/qwen3.8-27b"
    # qwen does not think out loud; only gpt-oss models get reasoning_effort.
    assert "reasoning_effort" not in sent
    roles = [m["role"] for m in sent["messages"]]
    assert roles == ["system", "user"]
    auth = _FakeAsyncClient.requests[-1]["headers"]["Authorization"]
    assert auth == "Bearer test-groq-key"

    with session_factory() as db:
        rows = (
            db.query(Transcript)
            .filter(Transcript.call_id == call_id)
            .order_by(Transcript.turn_index)
            .all()
        )
        assert [(r.speaker, r.text) for r in rows] == [
            ("caller", "My son was absent because he had a fever."),
            ("agent", "Sorry to hear that. How long has he been unwell?"),
        ]


def test_start_event_produces_opening_line_without_user_message(groq_client):
    token, _ = register(groq_client)
    call_id = start_session(groq_client, token)

    script(chat("Hello, this is an automated assistant calling about the absence. Is this Rahul's parent?"))
    resp = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "", "event": "start"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["done"] is False
    assert body["turn_index"] == 0
    # The opening is deterministic: disclosure + name + ONE question, no LLM
    # round trip (a model-written greeting repeated the identity twice and cost
    # a full provider call before the caller heard anything).
    assert "AI assistant calling from CMR" in body["reply_text"]
    # One question only, and it is the verification question - the reason for
    # the call comes after the caller confirms who they are.
    assert body["reply_text"].count("?") == 1
    assert "who I'm speaking with" in body["reply_text"]
    # No dangling substitution artifacts may ever be spoken.
    assert ", ," not in body["reply_text"]
    # Nothing was sent to the provider for the opening turn.
    assert _FakeAsyncClient.requests == []


def test_tool_calls_record_extracted_field_and_feed_result_back(groq_client, session_factory):
    from app.models import ExtractedField

    token, _ = register(groq_client)
    call_id = start_session(groq_client, token)

    # Round 1: model records the field; round 2: it speaks using the tool result.
    script(
        tool_call("record_extracted_field", {"field_name": "reason_for_absence", "value": "fever", "confidence": 0.92}),
        chat("Thanks, I have noted the fever. When did it start?"),
    )
    resp = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "He had fever since last night."},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["extracted_fields"] == [
        {"field_name": "reason_for_absence", "field_value": "fever", "confidence": 0.92}
    ]
    assert body["done"] is False

    # Second round-trip must carry the assistant tool_calls + role:"tool" result.
    second_request = _FakeAsyncClient.requests[1]["json"]
    roles = [m["role"] for m in second_request["messages"]]
    assert "assistant" in roles and "tool" in roles
    tool_msg = [m for m in second_request["messages"] if m["role"] == "tool"][0]
    assert "recorded reason_for_absence" in tool_msg["content"]

    with session_factory() as db:
        field = db.query(ExtractedField).filter(ExtractedField.call_id == call_id).one()
        assert field.field_name == "reason_for_absence"
        assert field.field_value == "fever"
        assert field.confidence == pytest.approx(0.92)


def test_end_call_tool_completes_session_with_summary(groq_client, session_factory):
    from app.models import Call

    token, _ = register(groq_client)
    call_id = start_session(groq_client, token)

    script(
        tool_call("end_call", {"summary": "Caller confirmed fever absence; will rejoin tomorrow."}, call_id="end_1"),
        chat("Thank you, wishing him a speedy recovery. Goodbye!"),
    )
    resp = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "Okay thank you, bye."},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["done"] is True
    assert "Goodbye" in body["reply_text"]
    assert body["extracted_fields"] == []

    with session_factory() as db:
        call = db.get(Call, call_id)
        assert call.status == "completed"
        assert call.summary == "Caller confirmed fever absence; will rejoin tomorrow."
        assert call.ended_at is not None

    # A completed session rejects further turns instead of silently continuing.
    further = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "hello again"},
        headers=auth_headers(token),
    )
    assert further.status_code == 409


def test_missing_groq_key_is_503(client):
    token, _ = register(client)
    call_id = start_session(client, token)
    resp = client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "hello"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 503
    assert "GROQ_API_KEY" in resp.json()["detail"]


def test_foreign_org_turn_is_404(groq_client):
    token_a, _ = register(groq_client, org_name="Org A", email="a@example.test")
    token_b, _ = register(groq_client, org_name="Org B", email="b@example.test")
    call_id = start_session(groq_client, token_a)

    foreign = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"event": "start"},
        headers=auth_headers(token_b),
    )
    assert foreign.status_code == 404
    # Nothing was consumed or persisted for the foreign attempt.
    assert _FakeAsyncClient.requests == []


def test_empty_text_is_422(groq_client):
    token, _ = register(groq_client)
    call_id = start_session(groq_client, token)
    resp = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "   "},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422


def test_turns_require_bearer(client):
    assert (
        client.post("/api/playground/sessions/1/turns", json={"text": "hi"}).status_code
        == 401
    )


def test_session_contact_persisted_and_injected_into_start_prompt(groq_client, session_factory):
    """P0-2: SessionCreate.contact is persisted on the call row and the
    personalization reaches the LLM prompt on the opening turn."""
    from app.models import Call

    token, _ = register(groq_client)
    ids = _make_agent_and_version(groq_client, token)
    session = groq_client.post(
        "/api/playground/sessions",
        json={
            "agent_version_id": ids["version"]["id"],
            "contact": {"student_name": "Aarav", "parent_name": "Suresh"},
        },
        headers=auth_headers(token),
    )
    assert session.status_code == 200, session.text
    call_id = int(session.json()["call_id"])

    with session_factory() as db:
        call = db.get(Call, call_id)
        assert call.context == {
            "contact": {"student_name": "Aarav", "parent_name": "Suresh"}
        }

    script(chat("Hello, this is an automated assistant calling about Aarav. May I speak with Suresh?"))
    resp = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "", "event": "start"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text

    # Personalization now happens in the deterministic opening itself, which
    # is stronger than hoping the model copies names into its greeting.
    opening = resp.json()["reply_text"]
    assert "Suresh" in opening
    # The parent is greeted and verified by name; the STUDENT is deliberately
    # not named in the opener (that comes after they confirm who they are).
    assert opening.count("Suresh") == 2  # "Hi Suresh" + "Am I speaking with Suresh?"
    assert "Aarav" not in opening
    assert "?" in opening

    # The same contact still reaches the LLM prompt on the next real turn.
    script(chat("Sure, I can help with that."))
    follow_up = groq_client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "yes, this is Suresh"},
        headers=auth_headers(token),
    )
    assert follow_up.status_code == 200, follow_up.text
    sent = _FakeAsyncClient.requests[-1]["json"]
    system_msg = sent["messages"][0]["content"]
    assert "Aarav" in system_msg and "Suresh" in system_msg
    # Both names are in the history the model reads, so it can introduce the
    # student naturally once the caller is confirmed.
    history = " ".join(m["content"] for m in sent["messages"][1:])
    assert "Suresh" in history


def test_history_trimmed_and_llm_leg_recorded(groq_client, session_factory):
    """10 exchanges keep the Groq payload bounded; the LLM leg is measured."""
    from sqlalchemy import select

    from app.models import Transcript

    token, _ = register(groq_client)
    call_id = start_session(groq_client, token)
    for i in range(10):
        script(chat(f"reply {i}"))
        resp = groq_client.post(
            f"/api/playground/sessions/{call_id}/turns",
            json={"text": f"caller says {i}"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200, resp.text
    sent = _FakeAsyncClient.requests[-1]["json"]
    # system + last 8 history rows + the new user turn. The window was 14 and
    # is now 8: Groq's TPM is organization-wide, so prompt tokens per turn are
    # the scarce resource, not the number of keys.
    from app.routers.playground import _MAX_HISTORY_ROWS

    assert len(sent["messages"]) == 1 + _MAX_HISTORY_ROWS + 1
    assert _MAX_HISTORY_ROWS == 6
    with session_factory() as db:
        rows = db.scalars(
            select(Transcript)
            .where(Transcript.call_id == call_id, Transcript.speaker == "agent")
            .order_by(Transcript.turn_index)
        ).all()
        assert len(rows) == 10
        assert all(r.llm_first_token_ms is not None for r in rows)
