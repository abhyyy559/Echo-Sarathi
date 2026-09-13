# P1 branch review package: 4d6a230..HEAD (code only; docs/superpowers are requirements inputs, not subjects)


# Commits

1202b24 docs: btn btn-primary correction in P1 plan Task 10 (review fix)
4bb7fc2 feat: campaign dry-run report UI and P2 exit-gate checklist
c0d4445 feat: handle pseudo tool-call markup and retry Groq 429s in text mode
6e3d222 docs: filter empty lead cards in P1 plan Task 9 (review fix)
bc35a43 fix: omit empty lead-card values in startSession; restore test-call button class
f9f0394 feat: contact-aware playground and test-call UI
12a0a0f docs: apply turns_used-1 correction in P1 plan Task 8
7c644f5 feat: text-mode campaign dry-run endpoint with scripted personas
10d8b9f docs: sync refuses persona wording in P1 plan Task 7
6d9c0ec feat: extract text-turn core and add dry-run caller personas
fa5e8dd feat: real-estate lead-qualification preset
02def22 feat: voice session speaks protected opening first
78b073d feat: voice token aliases and deterministic opening line builder
ed084e5 docs: correct test settings kwarg in P1 plan Task 3
130535c feat: test-call accepts version+contact, derives domain config when omitted
8fa04a5 docs: authorize ROLE & MISSION block in P1 plan Task 2 (review adjudication)
3a2efea feat: generic caller context, institution and token substitution in text prompt
df13d6a docs: fix lead-card assertion in P1 plan Task 2
a7cf265 feat: backend bracket-token substitution service with lead-gen aliases

# Stat

 backend/app/routers/agents.py                      |  33 +-
 backend/app/routers/playground.py                  | 312 +++++++--
 backend/app/routers/test_call.py                   |  36 +-
 backend/app/schemas.py                             |  39 +-
 backend/app/services/dry_run.py                    | 164 +++++
 backend/app/services/token_substitution.py         |  69 ++
 backend/tests/test_agents.py                       |  14 +-
 backend/tests/test_dry_run.py                      | 121 ++++
 backend/tests/test_playground_contact.py           |  58 ++
 backend/tests/test_testcall_contact.py             |  71 ++
 backend/tests/test_text_robustness.py              | 165 +++++
 backend/tests/test_token_substitution.py           |  62 ++
 .../presets/real-estate-lead-qualification.json    |  33 +
 frontend/src/api.js                                |  26 +-
 frontend/src/components/DryRunReport.jsx           |  75 +++
 frontend/src/components/LeadCardForm.jsx           |  75 +++
 frontend/src/components/TextPlayground.jsx         |  16 +-
 frontend/src/pages/CampaignDetailPage.jsx          |  47 +-
 frontend/src/pages/PlaygroundPage.jsx              | 717 ++++++++++++---------
 frontend/src/pages/TestCallPage.jsx                |  87 ++-
 voice-agent/app/pipeline.py                        |  67 +-
 voice-agent/app/prompting.py                       | 182 +++++-
 voice-agent/tests/test_opening_line.py             |  70 ++
 voice-agent/tests/test_token_substitution.py       |  91 +++
 24 files changed, 2239 insertions(+), 391 deletions(-)
diff --git a/backend/app/routers/agents.py b/backend/app/routers/agents.py
index abb9887..4a610ff 100644
--- a/backend/app/routers/agents.py
+++ b/backend/app/routers/agents.py
@@ -19,11 +19,11 @@ from pydantic import BaseModel, Field
 from sqlalchemy import select
 from sqlalchemy.orm import Session
 
 from app.database import get_db
 from app.deps import get_current_user, get_org_or_404, require_roles
-from app.models import AGENT_STATUSES, Agent, AgentVersion, User
+from app.models import AGENT_STATUSES, Agent, AgentVersion, DomainConfig, User
 from domain_config_schema import validate_agent_version_payload
 
 router = APIRouter(prefix="/api/agents", tags=["agents"])
 
 # Versions are also reachable directly by id (voice-agent + frontend use this).
@@ -314,5 +314,36 @@ def get_version(
     if version is None:
         raise HTTPException(status_code=404, detail="not found")
     # Org check through the parent agent (404 on foreign org GÇö no leak).
     get_org_or_404(db, Agent, version.agent_id, user.org_id)
     return _version_out(version)
+
+
+def ensure_domain_config(db: Session, agent: Agent, version: AgentVersion) -> DomainConfig:
+    """Find-or-create the legacy DomainConfig row anchoring an agent's phone path.
+
+    The voice brain is version-based, but campaigns and /api/test-call still
+    carry a ``domain_config_id`` FK. ``DomainConfig.name`` is globally unique,
+    so the auto row is namespaced per agent and never collides across orgs.
+    """
+    wanted = f"agent-{agent.id}-phone"
+    existing = db.scalar(select(DomainConfig).where(DomainConfig.name == wanted))
+    if existing is not None:
+        return existing
+    row = DomainConfig(
+        name=wanted,
+        display_name=agent.name,
+        config={
+            "domain_id": wanted,
+            "name": agent.name,
+            "version": version.version,
+            "system_prompt": version.system_prompt,
+            "mandatory_disclosure": version.disclosure_script,
+            "question_flow": version.question_flow or [],
+            "extraction_schema": version.extraction_schema or {},
+            "escalation_rules": version.escalation_rules or [],
+            "voice_settings": version.voice_settings or {},
+        },
+    )
+    db.add(row)
+    db.flush()
+    return row
diff --git a/backend/app/routers/playground.py b/backend/app/routers/playground.py
index eac680a..7a48e72 100644
--- a/backend/app/routers/playground.py
+++ b/backend/app/routers/playground.py
@@ -10,12 +10,14 @@ the backend talks to Groq directly, no LiveKit/telephony involved. The system
 prompt below is a slim server-side twin of voice-agent/app/prompting.py; the
 two services are deliberately decoupled.
 """
 from __future__ import annotations
 
+import asyncio
 import json
 import logging
+import re
 import time
 import uuid
 from datetime import timedelta
 from typing import Any, Optional
 
@@ -26,12 +28,14 @@ from sqlalchemy import select
 from sqlalchemy.orm import Session
 
 from app.config import Settings
 from app.database import get_db
 from app.deps import get_current_user, get_org_or_404
-from app.models import Agent, AgentVersion, Call, ExtractedField, Transcript, User
+from app.models import Agent, AgentVersion, Call, Campaign, Contact, ExtractedField, Organization, Transcript, User
+from app.schemas import DryRunCreate
 from app.timeutil import utcnow
+from app.services.token_substitution import apply_token_substitution, build_token_map
 
 logger = logging.getLogger(__name__)
 
 router = APIRouter(prefix="/api/playground", tags=["playground"])
 
@@ -39,10 +43,25 @@ _TOKEN_TTL = timedelta(hours=1)
 _LATENCY_METRICS = ("stt_final_ms", "llm_first_token_ms", "tts_first_audio_ms", "e2e_ms")
 
 _GROQ_BASE_URL = "https://api.groq.com/openai/v1"
 # Tool-call rounds per user turn before we force a plain-text reply.
 _MAX_TOOL_ROUNDS = 3
+_GROQ_MAX_RETRIES = 2
+_GROQ_RETRY_DELAYS = (2.0, 5.0)
+
+
+def _retry_delay(response: Any, attempt: int) -> float:
+    """Backoff for a 429: honor Retry-After, else 2s then 5s."""
+    try:
+        header = response.headers.get("retry-after")
+        if header is not None:
+            return max(0.0, float(header))
+    except (TypeError, ValueError, AttributeError):
+        pass
+    if 0 <= attempt < len(_GROQ_RETRY_DELAYS):
+        return _GROQ_RETRY_DELAYS[attempt]
+    return _GROQ_RETRY_DELAYS[-1]
 
 
 class SessionCreate(BaseModel):
     agent_version_id: int = Field(gt=0)
     # P0-2 personalization: flat {field: scalar} contact card (e.g.
@@ -298,23 +317,111 @@ def _question_text(item: Any) -> str:
     if isinstance(item, dict):
         return str(item.get("question") or item.get("text") or "").strip()
     return str(item or "").strip()
 
 
-def _render_text_system_prompt(config: Any, contact: Optional[dict[str, str]] = None) -> str:
+_GENERIC_SUBJECT_KEYS = ("full_name", "contact_name", "lead_name", "candidate_name", "name")
+_GENERIC_PARENT_KEYS = ("parent_name", "parent", "guardian", "contact_person")
+
+
+def _render_caller_context(contact: dict[str, str], institution: str) -> str:
+    """CALLER CONTEXT block that works for any domain, not just absent-student.
+
+    Known keys get human phrasing; every other supplied key is passed through
+    as a fact so domain-specific cards (city, budget, form_source, ...) still
+    reach the agent. With no contact, emits a do-not-invent-names guard.
+    """
+    lines = ["CALLER CONTEXT - who this specific call is about:"]
+    if institution:
+        lines.append(f"- You are calling from {institution}.")
+    if not contact:
+        lines.append(
+            "- You were NOT given the callee's name: NEVER invent or guess any name; "
+            "ask who you are speaking with."
+        )
+        return "\n".join(lines)
+
+    student = contact.get("student_name") or ""
+    parent = ""
+    for key in _GENERIC_PARENT_KEYS:
+        if contact.get(key):
+            parent = contact[key]
+            break
+    subject = ""
+    for key in _GENERIC_SUBJECT_KEYS:
+        if contact.get(key):
+            subject = contact[key]
+            break
+    about: list[str] = []
+    if student:
+        about.append(f"the student {student}")
+    if contact.get("class_section"):
+        about.append(f"class {contact['class_section']}")
+    if contact.get("absent_date"):
+        about.append(f"absent on {contact['absent_date']}")
+    if subject and subject != student:
+        about.append(f"the person {subject}")
+    if about:
+        lines.append("- You are calling about " + ", ".join(about) + ".")
+    else:
+        lines.append("- Details: " + json.dumps(contact, ensure_ascii=False))
+    woven = {"student_name", "class_section", "absent_date", *_GENERIC_SUBJECT_KEYS, *_GENERIC_PARENT_KEYS}
+    extras = {k: v for k, v in contact.items() if k not in woven}
+    if extras:
+        lines.append(
+            "- Other details you may use if relevant: "
+            + json.dumps(extras, ensure_ascii=False, sort_keys=True)
+        )
+    if parent:
+        lines.append(f"- Ask to speak with {parent} (the parent/guardian).")
+    elif subject:
+        lines.append(f"- Ask for {subject} when the call is answered.")
+
+    names: list[str] = []
+    for value in [parent, student, subject]:
+        if value and value not in names:
+            names.append(value)
+    if names:
+        lines.append(
+            "- SAY THE NAMES OUT LOUD: greet the person using their name. "
+            f"Known name(s) on this record: {', '.join(names)}."
+        )
+        lines.append(
+            "- NEVER say 'the parent or guardian of the student' or 'the person "
+            "we are calling about' when you have a real name on this record."
+        )
+    lines.extend(
+        [
+            "- VERIFY RELATIONSHIP BEFORE DETAILS: confirm you are speaking with the "
+            "right person before discussing any details.",
+            "- If the person who answered is NOT that person, do not share any details: "
+            "ask when they will be available, thank them politely, and end the call.",
+        ]
+    )
+    return "\n".join(lines)
+
+
+def _render_text_system_prompt(
+    config: Any,
+    contact: Optional[dict[str, str]] = None,
+    institution: str = "",
+) -> str:
     """Slim server-side twin of voice-agent/app/prompting.render_system_prompt.
 
     Same section order and discipline (disclosure verbatim first, TTS-safe
     style rules so text replies behave like the spoken ones), but compact
     enough to keep text-mode token cost low. ``contact`` (P0-2) appends the
     CALLER CONTEXT block so the agent personalizes and verifies the
     relationship before sharing any details.
     """
     sections: list[str] = []
 
+    card = contact or {}
+    tokens = build_token_map(card, institution=institution)
+
     # 1. Mandatory disclosure FIRST and verbatim.
-    disclosure = str(config.disclosure_script or "").strip()
+    disclosure = apply_token_substitution(str(config.disclosure_script or "").strip(), tokens)
     if disclosure:
         sections.append(
             f"MANDATORY DISCLOSURE - your VERY FIRST utterance, word-for-word:\n{disclosure}"
         )
 
@@ -322,54 +429,34 @@ def _render_text_system_prompt(config: Any, contact: Optional[dict[str, str]] =
     role_lines = [
         "You are a friendly human-sounding outbound phone agent; this is a TEXT test of that call.",
         "Every reply you type is read aloud by a speech engine exactly as written.",
         "Have a short natural conversation and complete the goals below.",
     ]
-    persona = str(config.system_prompt or "").strip()
-    if persona:
-        role_lines.append(f"Agent-specific role from the creator: {persona}")
+    persona = apply_token_substitution(str(config.system_prompt or "").strip(), tokens)
     sections.append(
         "WHO YOU ARE:\n" + "\n".join(f"- {line}" for line in role_lines)
     )
+    # 2b. Creator's role definition - authoritative, verbatim (not a bullet).
+    if persona:
+        sections.append(
+            "ROLE & MISSION - defined by the agent creator (AUTHORITATIVE):\n"
+            f"{persona}\n"
+            "This role definition is authoritative for WHO you are and HOW you "
+            "behave: where it differs from generic examples, follow the role "
+            "definition."
+        )
 
     # 3. Company context.
     company_context = config.company_context or {}
     if company_context:
         sections.append(
             "COMPANY KNOWLEDGE - facts you may use; never invent anything beyond this:\n"
             + json.dumps(company_context, ensure_ascii=False, default=str)
         )
 
-    # 3b. CALLER CONTEXT (P0-2) GÇö who this specific call is about.
-    if contact:
-        student = contact.get("student_name") or ""
-        parent = contact.get("parent_name") or ""
-        context_lines = ["CALLER CONTEXT - who this call is about:"]
-        about: list[str] = []
-        if student:
-            about.append(f"the student {student}")
-        if contact.get("class_section"):
-            about.append(f"class {contact['class_section']}")
-        if contact.get("absent_date"):
-            about.append(f"absent on {contact['absent_date']}")
-        if about:
-            context_lines.append("- You are calling about " + ", ".join(about) + ".")
-        else:
-            context_lines.append(
-                "- Details: " + json.dumps(contact, ensure_ascii=False)
-            )
-        if parent:
-            context_lines.append(f"- Ask to speak with {parent} (the parent/guardian).")
-        context_lines.extend(
-            [
-                "- VERIFY RELATIONSHIP BEFORE DETAILS: confirm you are speaking with the "
-                "parent/guardian before discussing any details.",
-                "- If the person who answered is NOT the parent/guardian, do not share any details: "
-                "ask when they will be available, thank them politely, and end the call.",
-            ]
-        )
-        sections.append("\n".join(context_lines))
+    # 3b. CALLER CONTEXT (P0-2, generic) GÇö who this specific call is about.
+    sections.append(_render_caller_context(card, institution))
 
     # 4. TTS-safe speaking style (kept identical in spirit to the voice agent).
     sections.append(
         "HOW TO REPLY (critical):\n"
         "- Keep every reply SHORT: usually 1-2 sentences, never more than 3.\n"
@@ -382,11 +469,11 @@ def _render_text_system_prompt(config: Any, contact: Optional[dict[str, str]] =
 
     # 5. Question flow as goals to weave in naturally.
     goals: list[str] = []
     number = 0
     for item in config.question_flow or []:
-        text_value = _question_text(item)
+        text_value = apply_token_substitution(_question_text(item), tokens)
         if not text_value:
             continue
         number += 1
         goals.append(f"{number}. {text_value}")
     if not goals:
@@ -502,11 +589,20 @@ async def _groq_chat(
     if not include_tools:
         body.pop("tools", None)
         body.pop("tool_choice", None)
     headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
     async with httpx.AsyncClient(base_url=_GROQ_BASE_URL, timeout=45.0) as client:
-        response = await client.post("/chat/completions", json=body, headers=headers)
+        response = None
+        for attempt in range(_GROQ_MAX_RETRIES + 1):
+            response = await client.post("/chat/completions", json=body, headers=headers)
+            if response.status_code != 429:
+                break
+            if attempt >= _GROQ_MAX_RETRIES:
+                break
+            logger.warning("Groq chat rate limited (429, attempt %s): backing off", attempt + 1)
+            await asyncio.sleep(_retry_delay(response, attempt))
+    assert response is not None  # loop always runs at least once
     if response.status_code == 429:
         logger.warning("Groq chat rate limited (429): %s", response.text[:300])
         raise HTTPException(
             status_code=429,
             detail="The AI service rate limit was hit. Wait a few seconds and send again.",
@@ -574,10 +670,41 @@ def _execute_text_tool(
         return "call ended", {"summary": summary}, True
 
     return f"error: unknown tool {name}", None, False
 
 
+_TOOL_CALL_BLOCK_RE = re.compile(r"<tool_call>.*?</tool_call>", re.DOTALL | re.IGNORECASE)
+_FUNCTION_RE = re.compile(r"<function\s*=\s*([^>\s]+)\s*>", re.IGNORECASE)
+_PARAMETER_RE = re.compile(r"<parameter\s*=\s*([^>\s]+)\s*>\s*(.*?)\s*</parameter>", re.DOTALL | re.IGNORECASE)
+_TAG_REMAINDER_RE = re.compile(r"</?(?:function|parameter)[^>]*>", re.IGNORECASE)
+
+
+def _parse_pseudo_tool_calls(text: str) -> list[dict[str, Any]]:
+    """Tool calls the model emitted as text instead of real function calls.
+
+    Returns [{name, arguments}]. Only ``record_extracted_field`` is actionable;
+    anything else is scrubbed but ignored (never terminate a call on echoed text).
+    """
+    found: list[dict[str, Any]] = []
+    for block in _TOOL_CALL_BLOCK_RE.findall(str(text or "")):
+        func = _FUNCTION_RE.search(block)
+        if not func:
+            continue
+        args: dict[str, Any] = {}
+        for key, value in _PARAMETER_RE.findall(block):
+            args[key.strip()] = value.strip()
+        found.append({"name": func.group(1).strip(), "arguments": args})
+    return found
+
+
+def _scrub_tool_markup(text: str) -> str:
+    """Remove tool-call markup so it never ships to the transcript/UI."""
+    out = _TOOL_CALL_BLOCK_RE.sub(" ", str(text or ""))
+    out = _TAG_REMAINDER_RE.sub(" ", out)
+    return " ".join(out.split())
+
+
 @router.post("/sessions/{call_id}/turns")
 async def create_turn(
     call_id: int,
     payload: TurnCreate,
     request: Request,
@@ -607,13 +734,33 @@ async def create_turn(
     start_event = payload.event == "start"
     user_text = "" if start_event else payload.text.strip()
     if not start_event and not user_text:
         raise HTTPException(status_code=422, detail="'text' must not be empty.")
 
-    system_prompt = _render_text_system_prompt(
-        version, contact=(call.context or {}).get("contact")
+    return await _run_agent_turn(
+        db, settings, call, version, user_text=user_text, start_event=start_event
     )
+
+
+async def _run_agent_turn(
+    db: Session,
+    settings: Settings,
+    call: Call,
+    version: AgentVersion,
+    *,
+    user_text: str,
+    start_event: bool,
+) -> dict[str, Any]:
+    """One text-mode agent turn: build prompt, call Groq, run tools, persist.
+
+    Shared by the HTTP turns endpoint and the campaign dry-run runner so
+    simulated calls go through byte-identical conversation logic.
+    """
+    contact = (call.context or {}).get("contact") or {}
+    org = db.get(Organization, call.org_id) if call.org_id else None
+    institution = org.name if org and org.name else ""
+    system_prompt = _render_text_system_prompt(version, contact=contact, institution=institution)
     history_rows = list(
         db.scalars(
             select(Transcript)
             .where(Transcript.call_id == call.id)
             .order_by(Transcript.turn_index, Transcript.id)
@@ -633,12 +780,13 @@ async def create_turn(
             "[Call just connected; the callee has not spoken yet] "
             "Produce ONLY your opening utterance now: the mandatory disclosure "
             "followed by a warm one-line greeting and your first question."
         )
         contact = (call.context or {}).get("contact") or {}
-        student = str(contact.get("student_name") or "").strip()
-        parent = str(contact.get("parent_name") or "").strip()
+        tokens = build_token_map(contact, institution)
+        student = tokens["[Student Name]"]
+        parent = tokens["[Parent/Guardian Name]"]
         if student:
             kickoff += (
                 f" You are calling about {student}"
                 + (f"; ask to speak with {parent}." if parent else ".")
             )
@@ -687,10 +835,24 @@ async def create_turn(
             messages + [{"role": "system", "content": "Reply now in plain words only."}],
             include_tools=False,
         )
         assistant_text = str(message.get("content") or "").strip()
 
+    # Pseudo tool calls: the model sometimes emits <tool_call> XML as text
+    # instead of a real function call (seen live: the field was lost and raw
+    # markup was saved to the transcript). Execute record_* ones with identical
+    # semantics, then scrub all markup so it never ships to the UI.
+    for pseudo in _parse_pseudo_tool_calls(assistant_text):
+        if pseudo["name"] != "record_extracted_field":
+            continue
+        _result_text, field_record, _done_flag = _execute_text_tool(
+            db, call, pseudo["name"], pseudo["arguments"], next_index
+        )
+        if field_record and "summary" not in field_record:
+            extracted_now.append(field_record)
+    assistant_text = _scrub_tool_markup(assistant_text)
+
     elapsed_ms = round((time.monotonic() - started_mono) * 1000.0)
 
     # Persist both sides of the exchange (caller turn only when not start).
     user_index: Optional[int] = None
     if user_text:
@@ -733,5 +895,73 @@ async def create_turn(
         "reply_text": assistant_text,
         "done": done,
         "extracted_fields": extracted_now,
         "turn_index": agent_index if assistant_text else next_index,
     }
+
+
+@router.post("/campaigns/{campaign_id}/dry-run")
+async def dry_run_campaign(
+    campaign_id: int,
+    payload: DryRunCreate,
+    request: Request,
+    user: User = Depends(get_current_user),
+    db: Session = Depends(get_db),
+) -> dict[str, Any]:
+    """SIMULATION ONLY: run campaign contacts through text-mode turns.
+
+    No telephony, no dialer. Each contact gets a scripted caller persona and
+    a persisted ``Call(kind="dry-run")`` for inspection via call detail.
+    """
+    from app.services.dry_run import PERSONA_ORDER, run_campaign_dry_run, validate_persona
+
+    settings: Settings = request.app.state.settings
+    if not settings.groq_api_key:
+        raise HTTPException(
+            status_code=503,
+            detail="Text mode needs GROQ_API_KEY configured on the backend.",
+        )
+    campaign = db.get(Campaign, campaign_id)
+    if campaign is None or campaign.org_id != user.org_id:
+        raise HTTPException(status_code=404, detail="not found")
+    version = None
+    if campaign.agent_version_id:
+        version = db.get(AgentVersion, campaign.agent_version_id)
+    if version is None:
+        version = db.scalar(
+            select(AgentVersion)
+            .join(Agent, Agent.id == AgentVersion.agent_id)
+            .where(Agent.org_id == user.org_id)
+            .order_by(AgentVersion.id.desc())
+        )
+    if version is None:
+        raise HTTPException(status_code=422, detail="no agent versions in org")
+    if payload.persona is not None:
+        try:
+            persona_names = [validate_persona(payload.persona)]
+        except ValueError as exc:
+            raise HTTPException(status_code=422, detail=str(exc)) from exc
+    else:
+        persona_names = list(PERSONA_ORDER)
+    contacts = list(
+        db.scalars(
+            select(Contact)
+            .where(
+                Contact.campaign_id == campaign.id,
+                Contact.status.in_(["queued", "pending_review"]),
+            )
+            .order_by(Contact.id)
+            .limit(payload.contact_limit)
+        ).all()
+    )
+    report = await run_campaign_dry_run(
+        db, settings, _run_agent_turn,
+        campaign=campaign, version=version,
+        contacts=contacts, persona_names=persona_names,
+    )
+    return {
+        "campaign_id": campaign.id,
+        "persona": payload.persona,
+        "contacts_total": len(contacts),
+        "contacts_run": len(report["results"]),
+        "results": report["results"],
+    }
diff --git a/backend/app/routers/test_call.py b/backend/app/routers/test_call.py
index 8245791..12845af 100644
--- a/backend/app/routers/test_call.py
+++ b/backend/app/routers/test_call.py
@@ -14,10 +14,11 @@ from sqlalchemy import select
 from sqlalchemy.orm import Session
 
 from app.database import get_db
 from app.deps import get_current_user
 from app.models import Agent, AgentVersion, Call, Campaign, Contact, DomainConfig, User
+from app.routers.agents import ensure_domain_config
 from app.schemas import TestCallOut, TestCallRequest
 from app.services.calls_service import log_call_event
 from app.services.import_service import normalize_phone
 from app.services.telephony import TelephonyClient
 from app.services.twilio_bridge import PHONE_ROOM_PREFIX
@@ -62,13 +63,10 @@ def place_test_call(
         raise HTTPException(
             status_code=422,
             detail=f"{target} is not in TEST_PHONE_NUMBERS; consent enforcement is on",
         )
 
-    if db.get(DomainConfig, payload.domain_config_id) is None:
-        raise HTTPException(status_code=422, detail="unknown domain_config_id")
-
     if payload.agent_version_id is not None:
         version = db.scalar(
             select(AgentVersion)
             .join(Agent, Agent.id == AgentVersion.agent_id)
             .where(AgentVersion.id == payload.agent_version_id, Agent.org_id == user.org_id)
@@ -84,35 +82,59 @@ def place_test_call(
             .limit(1)
         )
         if version is None:
             raise HTTPException(status_code=422, detail="no agent versions in org")
 
+    if payload.domain_config_id is not None:
+        if db.get(DomainConfig, payload.domain_config_id) is None:
+            raise HTTPException(status_code=422, detail="unknown domain_config_id")
+        domain_config_id = payload.domain_config_id
+    else:
+        agent = db.get(Agent, version.agent_id)
+        domain_config_id = ensure_domain_config(db, agent, version).id
+
     campaign = db.scalar(select(Campaign).where(Campaign.name == TEST_CAMPAIGN_NAME))
     if campaign is None:
         campaign = Campaign(
-            name=TEST_CAMPAIGN_NAME, domain_config_id=payload.domain_config_id, status="draft"
+            name=TEST_CAMPAIGN_NAME, domain_config_id=domain_config_id, status="draft"
         )
         db.add(campaign)
         db.flush()
-    elif campaign.domain_config_id != payload.domain_config_id:
-        campaign.domain_config_id = payload.domain_config_id
+    elif campaign.domain_config_id != domain_config_id:
+        campaign.domain_config_id = domain_config_id
 
     contact = db.scalar(
         select(Contact).where(Contact.campaign_id == campaign.id, Contact.phone == target)
     )
     if contact is None:
+        contact_card: dict[str, Any] = {
+            "name": payload.contact.get("name") if payload.contact else None,
+            "phone": target,
+            "status": "pending_review",
+            "consent": True,
+            "consent_source": "test_allowlist",
+        }
         contact = Contact(
             campaign_id=campaign.id,
-            name=f"Test Call ({target})",
+            name=contact_card["name"] or f"Test Call ({target})",
             phone=target,
             status="pending_review",
             consent=True,
             consent_source="test_allowlist",
         )
         db.add(contact)
         db.flush()
 
+    # Merge per-contact details (student_name, parent_name, class_section, ...)
+    # into custom_fields so they reach the voice agent's CALLER CONTEXT and the
+    # agent greets the RIGHT person by NAME instead of asking who it is calling.
+    details = dict(payload.contact or {})
+    if details:
+        merged = dict(contact.custom_fields or {})
+        merged.update(details)
+        contact.custom_fields = merged
+
     now = utcnow()
     call = Call(
         campaign_id=campaign.id,
         contact_id=contact.id,
         agent_version_id=version.id,
diff --git a/backend/app/schemas.py b/backend/app/schemas.py
index 210c6d0..04c3a7d 100644
--- a/backend/app/schemas.py
+++ b/backend/app/schemas.py
@@ -239,12 +239,16 @@ class CallListItemOut(BaseModel):
 # --- test call ----------------------------------------------------------------
 
 
 class TestCallRequest(BaseModel):
     to: Optional[str] = None
-    domain_config_id: int
+    domain_config_id: Optional[int] = None
     agent_version_id: Optional[int] = None  # phone leg: which agent version speaks
+    # Per-contact details the agent should know before it dials (student name,
+    # parent name, class, etc.). Stored into the contact's custom_fields and
+    # packed into the call room metadata so the agent greets the right person.
+    contact: Optional[dict[str, Any]] = None
 
 
 class TestCallOut(BaseModel):
     call_id: int
     provider_call_id: str
@@ -262,5 +266,38 @@ class InternalOk(BaseModel):
 class RetentionRunOut(BaseModel):
     cutoff: datetime
     calls_older_than_cutoff: int
     transcripts_deleted: int
     recording_urls_cleared: int
+
+
+# --- campaign dry-run (text-mode simulation) ---------------------------------
+
+
+class DryRunCreate(BaseModel):
+    persona: Optional[str] = None  # one of dry_run.PERSONA_ORDER; None = round-robin
+    contact_limit: int = Field(default=20, gt=0, le=100)
+
+
+class DryRunTranscriptTurn(BaseModel):
+    role: str
+    text: str
+
+
+class DryRunContactResult(BaseModel):
+    contact_id: int
+    name: str
+    phone: str  # masked
+    persona: str
+    transcript: list[DryRunTranscriptTurn]
+    extracted_fields: list[dict[str, Any]]
+    status: str
+    outcome: Optional[str] = None
+    turns: int
+
+
+class DryRunReport(BaseModel):
+    campaign_id: int
+    persona: Optional[str] = None
+    contacts_total: int
+    contacts_run: int
+    results: list[DryRunContactResult]
diff --git a/backend/app/services/dry_run.py b/backend/app/services/dry_run.py
new file mode 100644
index 0000000..2865a2b
--- /dev/null
+++ b/backend/app/services/dry_run.py
@@ -0,0 +1,164 @@
+"""Scripted caller personas for the text-mode campaign dry-run.
+
+Personas are positional scripts: reply N answers the agent's Nth utterance.
+They deliberately do NOT track conversation state GÇö the point is stressing
+the agent's confirmation loop, extraction precision, and wind-down behavior,
+not passing a Turing test. ``None`` means the persona has nothing left to
+say (runner stops the simulation for that lead).
+"""
+from __future__ import annotations
+
+from typing import Any, Mapping, Optional
+
+from sqlalchemy import select
+
+from app.timeutil import utcnow
+
+PERSONA_ORDER: tuple[str, ...] = ("cooperative", "terse", "distracted", "refuses", "clueless")
+
+_PERSONA_SCRIPTS: dict[str, list[str]] = {
+    "cooperative": [
+        "Yes, speaking.",
+        "He has had fever since yesterday.",
+        "He should be back on Monday.",
+        "Yes, I can submit the medical certificate tomorrow.",
+        "Thank you, goodbye.",
+    ],
+    "terse": ["Yes.", "Fever.", "Monday.", "Yes.", "Bye."],
+    "distracted": [
+        "Yes, speaking GÇö sorry, the TV is loud, one second.",
+        "Fever since yesterday. Ask my wife if you need the exact time, she tracks all that.",
+        "Monday, I think. Unless the doctor says rest longer, then Tuesday maybe.",
+        "Yes, certificate tomorrow. Anyway the traffic today was terrible.",
+        "Okay bye now.",
+    ],
+    "refuses": [
+        "I do not want to talk about this, please do not call again.",
+        "Please remove our number. Goodbye.",
+    ],
+    "clueless": [
+        "I don't know.",
+        "Not sure, you'd have to ask someone else.",
+        "I really couldn't say.",
+        "No idea. Is there anything else?",
+    ],
+}
+
+
+def validate_persona(name: str) -> str:
+    """Return the persona name or raise ValueError for unknown names."""
+    if name not in _PERSONA_SCRIPTS:
+        raise ValueError(f"unknown dry-run persona: {name!r}")
+    return name
+
+
+def persona_reply(
+    persona_name: str,
+    agent_text: str,
+    turn_no: int,
+    contact: Mapping[str, Any],
+) -> Optional[str]:
+    """Next scripted caller line, or None when the persona is done."""
+    script = _PERSONA_SCRIPTS[validate_persona(persona_name)]
+    if turn_no < 0 or turn_no >= len(script):
+        return None
+    return script[turn_no]
+
+
+_MAX_DRY_RUN_TURNS = 6
+
+
+def _mask_phone(phone: str) -> str:
+    text = str(phone or "")
+    if len(text) <= 4:
+        return "****"
+    return f"{text[:4]}****{text[-2:]}"
+
+
+def _contact_card(contact: Any) -> dict[str, str]:
+    card: dict[str, str] = {}
+    for key, value in ((contact.custom_fields or {}) if contact else {}).items():
+        name = str(key).strip()
+        if not name or isinstance(value, (dict, list)):
+            continue
+        text = str(value).strip()
+        if text:
+            card[name] = text
+    return card
+
+
+async def run_campaign_dry_run(
+    db: Any,
+    settings: Any,
+    run_turn: Any,
+    *,
+    campaign: Any,
+    version: Any,
+    contacts: list[Any],
+    persona_names: list[str],
+) -> dict[str, Any]:
+    """Simulate one text-mode call per contact against scripted personas.
+
+    Persists each simulation as a ``Call(kind="dry-run")`` so transcripts and
+    fields stay inspectable through the existing call-detail path. ``run_turn``
+    is ``_run_agent_turn`` injected for testability.
+    """
+    from app.models import Call, ExtractedField, Transcript  # local: avoids import cycles
+
+    results: list[dict[str, Any]] = []
+    for index, contact in enumerate(contacts):
+        persona = persona_names[index % len(persona_names)]
+        card = _contact_card(contact)
+        call = Call(
+            kind="dry-run",
+            status="in_progress",
+            org_id=campaign.org_id,
+            campaign_id=campaign.id,
+            contact_id=contact.id,
+            agent_version_id=version.id,
+            started_at=utcnow(),
+            context={"contact": card} if card else None,
+        )
+        db.add(call)
+        db.flush()
+
+        turns_used = 0
+        reply = await run_turn(db, settings, call, version, user_text="", start_event=True)
+        turns_used += 1
+        while not reply.get("done") and turns_used < _MAX_DRY_RUN_TURNS:
+            caller_line = persona_reply(persona, reply.get("reply_text") or "", turns_used - 1, card)
+            if not (caller_line or "").strip():
+                break
+            reply = await run_turn(db, settings, call, version, user_text=caller_line, start_event=False)
+            turns_used += 1
+        if call.status == "in_progress":
+            call.status = "completed"
+            call.ended_at = utcnow()
+        db.commit()
+
+        rows = db.scalars(
+            select(Transcript).where(Transcript.call_id == call.id).order_by(Transcript.turn_index)
+        ).all()
+        fields = db.scalars(
+            select(ExtractedField).where(ExtractedField.call_id == call.id).order_by(ExtractedField.id)
+        ).all()
+        results.append(
+            {
+                "contact_id": contact.id,
+                "name": contact.name,
+                "phone": _mask_phone(contact.phone),
+                "persona": persona,
+                "transcript": [
+                    {"role": ("agent" if r.speaker == "agent" else "caller"), "text": r.text}
+                    for r in rows
+                ],
+                "extracted_fields": [
+                    {"field_name": f.field_name, "field_value": f.field_value, "confidence": f.confidence}
+                    for f in fields
+                ],
+                "status": call.status,
+                "outcome": call.outcome,
+                "turns": turns_used,
+            }
+        )
+    return {"results": results}
diff --git a/backend/app/services/token_substitution.py b/backend/app/services/token_substitution.py
new file mode 100644
index 0000000..1f21d7b
--- /dev/null
+++ b/backend/app/services/token_substitution.py
@@ -0,0 +1,69 @@
+"""Bracket-token substitution ported from voice-agent/app/prompting.py.
+
+Keep the two in sync: KNOWN_TOKENS here must cover the same placeholder
+names the voice worker understands, plus the lead-gen aliases presets use
+([Lead Name], [Company Name], [Agent Name]).
+"""
+from __future__ import annotations
+
+import re
+from typing import Any, Mapping, Optional
+
+KNOWN_TOKENS: tuple[str, ...] = (
+    "[Institution Name]",
+    "[Company Name]",
+    "[Student Name]",
+    "[Lead Name]",
+    "[Parent/Guardian Name]",
+    "[Agent Name]",
+    "[Expected Return Date]",
+)
+
+_BRACKET_ARTIFACT_RE = re.compile(r"\[[^\]]*\]")
+_DOUBLE_SPACE_RE = re.compile(r"\s{2,}")
+
+_NAME_KEYS = ("student_name", "name", "contact_name", "full_name", "lead_name")
+_PARENT_KEYS = ("parent_name", "parent", "guardian", "contact_person")
+
+
+def _first(contact: Mapping[str, Any], keys: tuple[str, ...]) -> str:
+    for key in keys:
+        value = str(contact.get(key) or "").strip()
+        if value:
+            return value
+    return ""
+
+
+def build_token_map(
+    contact: Optional[Mapping[str, Any]] = None,
+    institution: str = "",
+    agent_name: str = "",
+) -> dict[str, str]:
+    """Resolve known placeholder tokens to real values for this call."""
+    card = contact if isinstance(contact, Mapping) else {}
+    name = _first(card, _NAME_KEYS)
+    parent = _first(card, _PARENT_KEYS)
+    org = str(institution or "").strip()
+    who = str(agent_name or "").strip() or "an AI assistant"
+    return {
+        "[Institution Name]": org,
+        "[Company Name]": org,
+        "[Student Name]": name,
+        "[Lead Name]": name,
+        "[Parent/Guardian Name]": parent,
+        "[Agent Name]": who,
+        "[Expected Return Date]": "",
+    }
+
+
+def apply_token_substitution(
+    text: str, tokens: Optional[Mapping[str, str]] = None
+) -> str:
+    """Replace known bracket tokens; empties removed, leftovers stripped."""
+    if not text:
+        return text
+    out = str(text)
+    for token, value in (tokens or {}).items():
+        out = out.replace(str(token), str(value) if value is not None else "")
+    out = _BRACKET_ARTIFACT_RE.sub("", out)
+    return _DOUBLE_SPACE_RE.sub(" ", out).strip()
diff --git a/backend/tests/test_agents.py b/backend/tests/test_agents.py
index 77b910c..4a304f3 100644
--- a/backend/tests/test_agents.py
+++ b/backend/tests/test_agents.py
@@ -52,11 +52,11 @@ def test_list_presets_returns_valid_payloads(client):
     assert resp.status_code == 200, resp.text
     presets = resp.json()
     ids = {p["preset_id"] for p in presets}
     # The four shipped role presets are present.
     assert {"lead-verification", "appointment-confirmation", "feedback-survey",
-            "absent-student-followup"} <= ids
+            "absent-student-followup", "real-estate-lead-qualification"} <= ids
     for preset in presets:
         assert preset["name"]
         payload = preset["version_payload"]
         # Each preset is a complete, saveable AgentVersion payload.
         assert payload["system_prompt"]
@@ -64,10 +64,22 @@ def test_list_presets_returns_valid_payloads(client):
         assert payload["extraction_schema"]
         assert payload["disclosure_script"]
         assert payload["escalation_rules"]
 
 
+def test_real_estate_preset_has_qualification_schema(client):
+    token, _user = register(client)
+    presets = client.get("/api/agents/presets", headers=auth_headers(token)).json()
+    payload = next(p for p in presets if p["preset_id"] == "real-estate-lead-qualification")["version_payload"]
+    assert set(payload["extraction_schema"]) >= {
+        "interest_level", "budget_band", "locality_preference",
+        "possession_timeline", "visit_date_preference", "call_outcome",
+        "escalation_needed",
+    }
+    assert len(payload["question_flow"]) == 5
+
+
 def test_preset_payload_saves_as_agent_version(client):
     """End-to-end contract: pick a preset, create an agent, save it as v1."""
     token, _user = register(client)
     presets = client.get(
         "/api/agents/presets", headers=auth_headers(token)
diff --git a/backend/tests/test_dry_run.py b/backend/tests/test_dry_run.py
new file mode 100644
index 0000000..ce6b4e8
--- /dev/null
+++ b/backend/tests/test_dry_run.py
@@ -0,0 +1,121 @@
+"""Dry-run personas: scripted callers behind the text-mode campaign dry-run."""
+from __future__ import annotations
+
+import pytest
+from sqlalchemy import select
+
+from app.services.dry_run import PERSONA_ORDER, persona_reply, validate_persona
+from conftest import auth_headers, register
+from test_playground_text import chat, groq_client, script, tool_call  # noqa: F401  (pytest fixture import)
+
+
+def _seed_campaign_with_contacts(session_factory, org_id, version_id):  # type: ignore[no-untyped-def]
+    from app.models import Campaign, Contact
+
+    with session_factory() as db:
+        campaign = Campaign(name="Dry-run Seeds", org_id=org_id, agent_version_id=version_id, status="draft")
+        db.add(campaign)
+        db.flush()
+        ids = []
+        for name, phone, custom in [
+            ("C1", "+919812345601", {"student_name": "Aarav", "parent_name": "Suresh"}),
+            ("C2", "+919812345602", {"student_name": "Ananya", "parent_name": "Rajesh"}),
+        ]:
+            contact = Contact(campaign_id=campaign.id, name=name, phone=phone, status="pending_review", custom_fields=custom)
+            db.add(contact)
+            db.flush()
+            ids.append(contact.id)
+        db.commit()
+        return campaign.id, ids
+
+
+def test_persona_order_covers_five_behaviors() -> None:
+    assert set(PERSONA_ORDER) == {"cooperative", "terse", "distracted", "refuses", "clueless"}
+
+
+def test_cooperative_answers_from_script() -> None:
+    reply = persona_reply("cooperative", "Why was Aarav absent?", 1, {"student_name": "Aarav"})
+    assert reply
+    assert "Aarav" not in reply  # caller answers; never parrots the agent's question
+
+
+def test_refuses_ends_early() -> None:
+    first = persona_reply("refuses", "Hello?", 0, {})
+    assert first is not None and "not" in first.lower()
+    assert persona_reply("refuses", "Why?", 5, {}) is None
+
+
+def test_terse_is_short() -> None:
+    reply = persona_reply("terse", "Why was Aarav absent?", 1, {})
+    assert reply is not None and len(reply.split()) <= 3
+
+
+def test_unknown_persona_rejected() -> None:
+    with pytest.raises(ValueError):
+        validate_persona("sarcastic")
+
+
+def test_mask_phone() -> None:
+    from app.services.dry_run import _mask_phone
+
+    assert _mask_phone("+919812345601") == "+919****01"
+    assert _mask_phone("123") == "****"
+
+
+def test_dry_run_runs_contacts_and_records_fields(groq_client, session_factory):
+    from test_agents import version_payload
+    from test_playground import _make_agent_and_version
+    from test_playground_text import chat, script, tool_call
+
+    from app.models import Call
+
+    client = groq_client
+    token, user = register(client)
+    ids = _make_agent_and_version(client, token)
+    campaign_id, contact_ids = _seed_campaign_with_contacts(
+        session_factory, user["org_id"], ids["version"]["id"]
+    )
+
+    # NB: after each end_call tool the round loop makes one more Groq call
+    # before returning, so every end_call needs a trailing spare chat message.
+    script(
+        chat("Hello, disclosure line. Am I speaking with Suresh?"),
+        tool_call("record_extracted_field", {"field_name": "reason_for_absence", "value": "fever", "confidence": 0.9}),
+        chat("Thanks, noted the fever."),
+        tool_call("end_call", {"summary": "fever; back Monday"}),
+        chat("Noted, goodbye."),
+        chat("Hello, disclosure line. Am I speaking with Suresh?"),
+        tool_call("end_call", {"summary": "refused"}),
+        chat("Understood, goodbye."),
+    )
+    resp = client.post(
+        f"/api/playground/campaigns/{campaign_id}/dry-run",
+        json={"persona": "cooperative"},
+        headers=auth_headers(token),
+    )
+    assert resp.status_code == 200, resp.text
+    report = resp.json()
+    assert report["contacts_run"] == 2
+    first, second = report["results"]
+    assert first["extracted_fields"] and first["extracted_fields"][0]["field_name"] == "reason_for_absence"
+    assert first["phone"].endswith("01") and "****" in first["phone"]
+    assert len(first["transcript"]) >= 2
+    assert report["results"][1]["status"] == "completed"
+    with session_factory() as db:
+        rows = db.scalars(select(Call).where(Call.campaign_id == campaign_id)).all()
+        assert rows and all(c.kind == "dry-run" for c in rows)
+
+
+def test_dry_run_rejects_unknown_persona(groq_client, session_factory):
+    from test_playground import _make_agent_and_version
+
+    client = groq_client
+    token, user = register(client)
+    ids = _make_agent_and_version(client, token)
+    campaign_id, _ = _seed_campaign_with_contacts(session_factory, user["org_id"], ids["version"]["id"])
+    resp = client.post(
+        f"/api/playground/campaigns/{campaign_id}/dry-run",
+        json={"persona": "sarcastic"},
+        headers=auth_headers(token),
+    )
+    assert resp.status_code == 422
diff --git a/backend/tests/test_playground_contact.py b/backend/tests/test_playground_contact.py
new file mode 100644
index 0000000..c8f2334
--- /dev/null
+++ b/backend/tests/test_playground_contact.py
@@ -0,0 +1,58 @@
+"""Generic caller context + token substitution in the text-mode prompt."""
+from __future__ import annotations
+
+from types import SimpleNamespace
+from typing import Any
+
+from app.routers.playground import _render_caller_context, _render_text_system_prompt
+
+
+def _config(**overrides: Any) -> Any:
+    base: dict[str, Any] = {
+        "disclosure_script": "Hi, this is [Agent Name] calling from [Institution Name].",
+        "system_prompt": "You call about [Student Name].",
+        "company_context": {},
+        "question_flow": [{"step": 1, "question": "Why was [Student Name] absent?"}],
+        "extraction_schema": {},
+    }
+    base.update(overrides)
+    return SimpleNamespace(**base)
+
+
+def test_absent_student_card_names_and_institution() -> None:
+    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar", "class_section": "10-A"}
+    prompt = _render_text_system_prompt(_config(), contact=contact, institution="Demo School")
+    assert "Aarav Kumar" in prompt
+    assert "Suresh Kumar" in prompt
+    assert "Demo School" in prompt
+    assert "[Student Name]" not in prompt
+    assert "[Institution Name]" not in prompt
+    assert "Why was Aarav Kumar absent?" in prompt
+
+
+def test_lead_style_card_generic_phrasing() -> None:
+    contact = {"lead_name": "Riya", "city": "Hyderabad"}
+    block = _render_caller_context(contact, "Acme Realty")
+    assert "Riya" in block
+    assert "Hyderabad" in block
+    assert "the person Riya" in block
+    assert "absent" not in block.lower()
+    assert "class_section" not in block
+
+
+def test_empty_contact_guards_against_invented_names() -> None:
+    block = _render_caller_context({}, "")
+    assert "NEVER invent or guess any name" in block
+    prompt = _render_text_system_prompt(_config(), contact=None, institution="")
+    assert "CALLER CONTEXT" in prompt
+    assert "NEVER invent or guess any name" in prompt
+
+
+def test_empty_institution_drops_cleanly() -> None:
+    prompt = _render_text_system_prompt(_config(), contact={"student_name": "Aarav"}, institution="")
+    assert "Aarav" in prompt
+    assert "[Institution Name]" not in prompt
+    # Scoped: the static HOW-TO-REPLY block intentionally uses two-space
+    # indentation, so the no-gap check applies to substituted text only.
+    disclosure_line = next(l for l in prompt.splitlines() if "AI assistant calling from" in l)
+    assert "  " not in disclosure_line
diff --git a/backend/tests/test_testcall_contact.py b/backend/tests/test_testcall_contact.py
new file mode 100644
index 0000000..4d7a462
--- /dev/null
+++ b/backend/tests/test_testcall_contact.py
@@ -0,0 +1,71 @@
+"""Contact-aware test calls: version pin + lead card + derived domain config."""
+from __future__ import annotations
+
+from typing import Any
+
+from conftest import auth_headers, make_settings, register
+from test_agents import version_payload
+from test_playground import _make_agent_and_version
+
+
+def _test_number_app(session_factory):  # type: ignore[no-untyped-def]
+    from fastapi.testclient import TestClient
+
+    from app.main import create_app
+
+    fresh = create_app(
+        make_settings(test_phone_numbers="+919812345601")
+    )
+    fresh.state.session_factory = session_factory
+    return fresh
+
+
+def test_test_call_forwards_version_and_contact(client, session_factory):
+    from fastapi.testclient import TestClient
+
+    from app.models import Call, Contact
+
+    token, user = register(client)
+    ids = _make_agent_and_version(client, token)
+    version_id = ids["version"]["id"]
+    with TestClient(_test_number_app(session_factory)) as numbered:
+        resp = numbered.post(
+            "/api/test-call",
+            json={
+                "to": "+919812345601",
+                "agent_version_id": version_id,
+                "contact": {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"},
+            },
+            headers=auth_headers(token),
+        )
+    assert resp.status_code == 200, resp.text
+    body = resp.json()
+    assert body["provider_call_id"].startswith("CAfake")
+    with session_factory() as db:
+        call = db.get(Call, body["call_id"])
+        assert call.agent_version_id == version_id
+        contact = db.get(Contact, call.contact_id)
+        assert contact.custom_fields["student_name"] == "Aarav Kumar"
+        assert contact.custom_fields["parent_name"] == "Suresh Kumar"
+
+
+def test_test_call_derives_domain_config_when_omitted(client, session_factory):
+    from fastapi.testclient import TestClient
+
+    from app.models import Call, DomainConfig
+
+    token, _user = register(client)
+    ids = _make_agent_and_version(client, token)
+    with TestClient(_test_number_app(session_factory)) as numbered:
+        resp = numbered.post(
+            "/api/test-call",
+            json={"to": "+919812345601", "agent_version_id": ids["version"]["id"]},
+            headers=auth_headers(token),
+        )
+    assert resp.status_code == 200, resp.text
+    with session_factory() as db:
+        call = db.get(Call, resp.json()["call_id"])
+        derived = db.get(DomainConfig, call.campaign.domain_config_id)
+        assert derived is not None
+        assert derived.name.startswith(f"agent-{ids['agent']['id']}-")
+        assert "system_prompt" in (derived.config or {})
diff --git a/backend/tests/test_text_robustness.py b/backend/tests/test_text_robustness.py
new file mode 100644
index 0000000..0a30f04
--- /dev/null
+++ b/backend/tests/test_text_robustness.py
@@ -0,0 +1,165 @@
+"""Text-path robustness: pseudo tool-call markup + Groq 429 retry."""
+from __future__ import annotations
+
+from typing import Any
+
+import pytest
+from fastapi.testclient import TestClient
+
+import app.routers.playground as playground_module
+from conftest import auth_headers, register
+from test_playground_text import chat, create_groq_app, groq_client, script, start_session  # noqa: F401  (pytest fixture import)
+
+
+def test_parse_and_scrub_pseudo_tool_call() -> None:
+    from app.routers.playground import _parse_pseudo_tool_calls, _scrub_tool_markup
+
+    text = (
+        "ok <tool_call>\n<function=record_extracted_field>\n<parameter=confidence>\n0.95\n</parameter>\n"
+        "<parameter=field_name>\nis_sick_leave\n</parameter>\n<parameter=value>\nyes\n</parameter>\n"
+        "</function>\n</tool_call> done"
+    )
+    calls = _parse_pseudo_tool_calls(text)
+    assert len(calls) == 1
+    assert calls[0]["name"] == "record_extracted_field"
+    assert calls[0]["arguments"] == {"confidence": "0.95", "field_name": "is_sick_leave", "value": "yes"}
+    assert _scrub_tool_markup(text) == "ok done"
+
+
+def test_pseudo_tool_call_recorded_and_scrubbed(groq_client, session_factory):
+    from sqlalchemy import select
+
+    from app.models import ExtractedField, Transcript
+
+    client = groq_client
+    token, _ = register(client)
+    call_id = start_session(client, token)
+    pseudo = (
+        "<tool_call>\n<function=record_extracted_field>\n<parameter=confidence>\n0.95\n</parameter>\n"
+        "<parameter=field_name>\nis_sick_leave\n</parameter>\n<parameter=value>\nyes\n</parameter>\n"
+        "</function>\n</tool_call>"
+    )
+    script(chat(pseudo))
+    resp = client.post(
+        f"/api/playground/sessions/{call_id}/turns",
+        json={"text": "He is sick."},
+        headers=auth_headers(token),
+    )
+    assert resp.status_code == 200, resp.text
+    body = resp.json()
+    assert body["extracted_fields"] == [
+        {"field_name": "is_sick_leave", "field_value": "yes", "confidence": 0.95}
+    ]
+    assert "<tool_call>" not in body["reply_text"]
+    with session_factory() as db:
+        fields = db.scalars(
+            select(ExtractedField).where(ExtractedField.call_id == call_id)
+        ).all()
+        assert [(f.field_name, f.field_value) for f in fields] == [("is_sick_leave", "yes")]
+        texts = [
+            t.text
+            for t in db.scalars(
+                select(Transcript).where(Transcript.call_id == call_id).order_by(Transcript.turn_index)
+            ).all()
+        ]
+        assert all("<tool_call>" not in t for t in texts)
+
+
+def test_pseudo_tool_call_mixed_text_kept(groq_client):
+    client = groq_client
+    token, _ = register(client)
+    call_id = start_session(client, token)
+    pseudo = (
+        "Noted. <tool_call>\n<function=record_extracted_field>\n<parameter=confidence>\n0.9\n</parameter>\n"
+        "<parameter=field_name>\nreason_for_absence\n</parameter>\n<parameter=value>\nfever\n</parameter>\n"
+        "</function>\n</tool_call>"
+    )
+    script(chat(pseudo))
+    resp = client.post(
+        f"/api/playground/sessions/{call_id}/turns",
+        json={"text": "He has fever."},
+        headers=auth_headers(token),
+    )
+    assert resp.status_code == 200, resp.text
+    assert resp.json()["reply_text"] == "Noted."
+    assert resp.json()["extracted_fields"][0]["field_name"] == "reason_for_absence"
+
+
+class _FlakyResponse:
+    def __init__(self, status_code: int, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> None:
+        self.status_code = status_code
+        self._payload = payload or {}
+        self.headers = headers or {}
+        self.text = "rate limited" if status_code == 429 else ""
+
+    def json(self) -> dict[str, Any]:
+        return self._payload
+
+
+class _FlakyAsyncClient:
+    planned: list[_FlakyResponse] = []
+    requests: list[dict[str, Any]] = []
+
+    def __init__(self, **_kwargs: Any) -> None:
+        pass
+
+    async def __aenter__(self) -> "_FlakyAsyncClient":
+        return self
+
+    async def __aexit__(self, *_exc: Any) -> bool:
+        return False
+
+    async def post(self, url: str | None = None, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> _FlakyResponse:
+        _FlakyAsyncClient.requests.append({"url": url, "json": json, "headers": headers})
+        assert _FlakyAsyncClient.planned, "no planned response left"
+        return _FlakyAsyncClient.planned.pop(0)
+
+
+@pytest.fixture()
+def flaky_client(session_factory, monkeypatch):  # type: ignore[no-untyped-def]
+    monkeypatch.setattr(playground_module.httpx, "AsyncClient", _FlakyAsyncClient)
+    _FlakyAsyncClient.planned = []
+    _FlakyAsyncClient.requests = []
+    fresh = create_groq_app(session_factory)
+    with TestClient(fresh) as test_client:
+        yield test_client
+    _FlakyAsyncClient.planned = []
+    _FlakyAsyncClient.requests = []
+
+
+def test_groq_429_retries_then_succeeds(flaky_client):
+    from test_playground_text import start_session as _start
+
+    client = flaky_client
+    token, _ = register(client)
+    call_id = _start(client, token)
+    _FlakyAsyncClient.planned = [
+        _FlakyResponse(429, headers={"retry-after": "0"}),
+        _FlakyResponse(200, {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}),
+    ]
+    _FlakyAsyncClient.requests = []
+    resp = client.post(
+        f"/api/playground/sessions/{call_id}/turns",
+        json={"text": "hi"},
+        headers=auth_headers(token),
+    )
+    assert resp.status_code == 200, resp.text
+    assert resp.json()["reply_text"] == "hi"
+    assert len(_FlakyAsyncClient.requests) == 2
+
+
+def test_groq_persistent_429_raises_after_retries(flaky_client):
+    from test_playground_text import start_session as _start
+
+    client = flaky_client
+    token, _ = register(client)
+    call_id = _start(client, token)
+    _FlakyAsyncClient.planned = [_FlakyResponse(429, headers={"retry-after": "0"})] * 3
+    _FlakyAsyncClient.requests = []
+    resp = client.post(
+        f"/api/playground/sessions/{call_id}/turns",
+        json={"text": "hi"},
+        headers=auth_headers(token),
+    )
+    assert resp.status_code == 429
+    assert len(_FlakyAsyncClient.requests) == 3  # initial + 2 retries
diff --git a/backend/tests/test_token_substitution.py b/backend/tests/test_token_substitution.py
new file mode 100644
index 0000000..749ecbf
--- /dev/null
+++ b/backend/tests/test_token_substitution.py
@@ -0,0 +1,62 @@
+"""Bracket-token substitution ported from voice-agent/app/prompting.py."""
+from __future__ import annotations
+
+from app.services.token_substitution import (
+    KNOWN_TOKENS,
+    apply_token_substitution,
+    build_token_map,
+)
+
+
+def test_known_tokens_cover_lead_gen_aliases() -> None:
+    assert set(KNOWN_TOKENS) >= {
+        "[Institution Name]",
+        "[Company Name]",
+        "[Student Name]",
+        "[Lead Name]",
+        "[Parent/Guardian Name]",
+        "[Agent Name]",
+        "[Expected Return Date]",
+    }
+
+
+def test_build_token_map_resolves_names_and_institution() -> None:
+    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
+    tokens = build_token_map(contact, institution="Demo School")
+    assert tokens["[Student Name]"] == "Aarav Kumar"
+    assert tokens["[Parent/Guardian Name]"] == "Suresh Kumar"
+    assert tokens["[Institution Name]"] == "Demo School"
+    assert tokens["[Company Name]"] == "Demo School"
+
+
+def test_build_token_map_lead_style_contact() -> None:
+    tokens = build_token_map({"lead_name": "Riya", "city": "Hyderabad"}, institution="Acme Realty")
+    assert tokens["[Lead Name]"] == "Riya"
+    assert tokens["[Student Name]"] == "Riya"
+
+
+def test_build_token_map_agent_name_defaults_to_assistant() -> None:
+    assert build_token_map({})["[Agent Name]"] == "an AI assistant"
+    assert build_token_map({}, agent_name="Priya")["[Agent Name]"] == "Priya"
+
+
+def test_apply_token_substitution_replaces_and_drops_empties() -> None:
+    tokens = build_token_map({"student_name": "Aarav"}, institution="")
+    out = apply_token_substitution(
+        "Hello [Parent/Guardian Name], calling from [Institution Name] about [Student Name].",
+        tokens,
+    )
+    assert "[Parent/Guardian Name]" not in out
+    assert "[Institution Name]" not in out
+    assert "Aarav" in out
+    assert "  " not in out
+
+
+def test_apply_token_substitution_strips_unknown_brackets() -> None:
+    out = apply_token_substitution("See [Something Else] today.", {})
+    assert "[" not in out and "]" not in out
+    assert out == "See today."
+
+
+def test_apply_token_substitution_falsy_passthrough() -> None:
+    assert apply_token_substitution("", {}) == ""
diff --git a/domain-configs/presets/real-estate-lead-qualification.json b/domain-configs/presets/real-estate-lead-qualification.json
new file mode 100644
index 0000000..b8da1cd
--- /dev/null
+++ b/domain-configs/presets/real-estate-lead-qualification.json
@@ -0,0 +1,33 @@
+{
+  "preset_id": "real-estate-lead-qualification",
+  "name": "Real-Estate Lead Qualification Agent",
+  "description": "Calls people who enquired about a property, confirms genuine interest, qualifies budget/locality/timeline, and books the next step (site visit or call-back).",
+  "version_payload": {
+    "system_prompt": "# ROLE\nYou are a lead qualification agent for [Company Name], a real-estate brokerage. You call people who recently enquired about a property (website form, listing, or referral).\n\n# OBJECTIVE\nConfirm the person is genuinely interested, understand their requirement (budget band, preferred locality, possession timeline), and agree a concrete next step: a site visit or a call-back. Your job is qualification, NOT closing the sale.\n\n# PERSONA & TONE\nWarm, professional, unhurried. The whole call should take 2-3 minutes. Never pushy, never argue.\n\n# OPENING\n\"Hi [Lead Name], this is [Agent Name] calling from [Company Name] regarding the property enquiry you submitted recently. Do you have a couple of minutes?\"\n\n# THINGS TO FIND OUT\n1. Confirm they actually made the enquiry (if not, apologise politely and end the call).\n2. Confirm their interest in the property type is still current.\n3. Understand the requirement: budget band, preferred locality, possession timeline.\n4. Agree the next step: site visit date or a better time to call back.\n\n# ANSWERING PROPERTY QUESTIONS\nAnswer only basic property questions whose facts are in your company knowledge (size, price band, amenities, location). If a fact is not in your knowledge, say you will have a specialist confirm it GÇö never quote a number you were not given.\n\n# OBJECTIONS & FAQ\n- \"I never enquired.\" -> Apologise sincerely, mention the enquiry source if you have it, and end the call politely. Flag the lead as invalid.\n- \"Just send me the details on WhatsApp.\" -> Offer to have the team send details after this quick qualification.\n- \"I'm busy right now.\" -> Ask for a better time, note it, thank them, and end the call.\n- \"How did you get my number?\" -> \"You shared it in the enquiry you submitted.\"\n\n# DO NOT\n- Never quote prices, offers, or possession dates beyond your company knowledge.\n- Never share other people's information.\n- Never continue the call if the person says they are not interested - thank them and end it.",
+    "company_context": {"company_name": "[Company Name]", "price_bands": "[Price bands served]", "areas_served": "[Areas served]", "sample_listing_facts": "[Size / price band / amenities of the featured property]"},
+    "question_flow": [
+      {"step": 1, "question": "Did you recently enquire about a property with [Company Name]?"},
+      {"step": 2, "question": "Are you still looking to buy?"},
+      {"step": 3, "question": "What budget band and locality are you considering?"},
+      {"step": 4, "question": "By when are you hoping to take possession?"},
+      {"step": 5, "question": "Would you like to schedule a site visit, or should I call back at a better time?"}
+    ],
+    "extraction_schema": {
+      "interest_level": {"type": "string", "description": "Lead interest: hot, warm, cold, or not_interested.", "validation": "required", "confidence_threshold": 0.8},
+      "budget_band": {"type": "string", "description": "Budget band exactly as the lead stated it.", "validation": "required", "confidence_threshold": 0.8},
+      "locality_preference": {"type": "string", "description": "Preferred locality or area.", "validation": "required", "confidence_threshold": 0.8},
+      "possession_timeline": {"type": "string", "description": "When the lead hopes to take possession.", "validation": "optional", "confidence_threshold": 0.7},
+      "visit_date_preference": {"type": "string", "description": "Preferred site-visit date/time, if offered.", "validation": "optional", "confidence_threshold": 0.7},
+      "call_outcome": {"type": "string", "description": "Outcome: qualified, callback_requested, not_interested, or invalid_lead.", "validation": "required", "confidence_threshold": 0.8},
+      "escalation_needed": {"type": "boolean", "description": "True when a human must review (abuse, legal question, contradiction).", "validation": "optional", "confidence_threshold": 0.9}
+    },
+    "disclosure_script": "Hello, this is [Agent Name] calling from [Company Name]. I am an AI voice assistant calling about your property enquiry. This call is recorded for quality purposes.",
+    "escalation_rules": [
+      {"trigger": "Caller asks a detailed pricing, legal, or availability question.", "action": "flag"},
+      {"trigger": "Caller requests to opt out of all calls.", "action": "end_call"},
+      {"trigger": "Caller is angry or abusive.", "action": "end_call"},
+      {"trigger": "Caller asks to speak with a human representative.", "action": "flag"}
+    ],
+    "voice_settings": {"language": "en", "stt_language": "en", "speaking_rate": 1.0, "llm_model": "", "tts_voice_id": "", "voices_by_language": {"en": ""}}
+  }
+}
diff --git a/frontend/src/api.js b/frontend/src/api.js
index 956ee8d..bc3297b 100644
--- a/frontend/src/api.js
+++ b/frontend/src/api.js
@@ -155,22 +155,36 @@ export const agentsApi = {
   listVersions: (agentId) => apiFetch(`/api/agents/${agentId}/versions`),
   getVersion: (versionId) => apiFetch(`/api/agent-versions/${versionId}`),
 };
 
 export const playgroundApi = {
-  startSession: (agentVersionId) =>
-    apiFetch('/api/playground/sessions', {
+  startSession: (agentVersionId, contact) => {
+    const card = Object.fromEntries(
+      Object.entries(contact || {}).filter(([, v]) => String(v ?? '').trim())
+    );
+    return apiFetch('/api/playground/sessions', {
       method: 'POST',
-      body: JSON.stringify({ agent_version_id: agentVersionId }),
-    }),
+      body: JSON.stringify(
+        Object.keys(card).length
+          ? { agent_version_id: agentVersionId, contact: card }
+          : { agent_version_id: agentVersionId }
+      ),
+    });
+  },
   completeSession: (callId) => apiFetch(`/api/playground/sessions/${callId}/complete`, { method: 'POST' }),
   // Text mode: one conversational turn (or {event:'start'} for the opening line).
   sendTurn: (callId, body) =>
     apiFetch(`/api/playground/sessions/${callId}/turns`, {
       method: 'POST',
       body: JSON.stringify(body),
     }),
+  // SIMULATION ONLY: run campaign contacts through text-mode turns. No telephony.
+  runDryRun: (campaignId, body) =>
+    apiFetch(`/api/playground/campaigns/${campaignId}/dry-run`, {
+      method: 'POST',
+      body: JSON.stringify(body || {}),
+    }),
 };
 
 export const devApi = {
   /** No auth required by design GÇö safe to poll before login. */
   health: () => apiFetch('/api/health'),
@@ -218,5 +232,9 @@ export const api = {
 };
 
 export function campaignExportUrl(campaignId, format) {
   return `${API_BASE}/api/campaigns/${campaignId}/export?format=${encodeURIComponent(format)}`;
 }
+
+export function callExportUrl(callId, format) {
+  return `${API_BASE}/api/calls/${callId}/export?format=${encodeURIComponent(format)}`;
+}
diff --git a/frontend/src/components/DryRunReport.jsx b/frontend/src/components/DryRunReport.jsx
new file mode 100644
index 0000000..ff8185d
--- /dev/null
+++ b/frontend/src/components/DryRunReport.jsx
@@ -0,0 +1,75 @@
+import React from 'react';
+import StatusBadge from './StatusBadge.jsx';
+
+/** Per-contact accordion for a DryRunReport. Includes a client-side CSV download. */
+export default function DryRunReport({ report }) {
+  if (!report) return null;
+  const results = report.results || [];
+
+  function downloadCsv() {
+    const header = ['contact_id', 'name', 'phone', 'persona', 'status', 'outcome', 'turns', 'fields'];
+    const lines = [header.join(',')];
+    for (const r of results) {
+      const fields = (r.extracted_fields || [])
+        .map((f) => `${f.field_name}=${f.field_value}`)
+        .join('; ')
+        .replace(/"/g, '""');
+      lines.push(
+        [r.contact_id, `"${r.name || ''}"`, r.phone, r.persona, r.status, `"${r.outcome || ''}"`, r.turns, `"${fields}"`].join(',')
+      );
+    }
+    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
+    const url = URL.createObjectURL(blob);
+    const a = document.createElement('a');
+    a.href = url;
+    a.download = `dry-run-campaign-${report.campaign_id}.csv`;
+    a.click();
+    URL.revokeObjectURL(url);
+  }
+
+  return (
+    <div className="card">
+      <div className="page-head">
+        <div>
+          <h3 className="page-title">Dry-run report (SIMULATION GÇö no calls placed)</h3>
+          <p className="page-sub">
+            {report.contacts_run} of {report.contacts_total} contacts simulated
+            {report.persona ? ` -+ persona: ${report.persona}` : ' -+ personas: round-robin'}.
+          </p>
+        </div>
+        <div className="form-actions">
+          <button className="btn btn-secondary btn-sm" onClick={downloadCsv}>
+            Download CSV
+          </button>
+        </div>
+      </div>
+      {results.map((r) => (
+        <details key={r.contact_id} className="card">
+          <summary>
+            {r.name} -+ {r.phone} -+ <StatusBadge status={r.status} /> -+ {r.persona} -+ {r.turns} turns
+          </summary>
+          <h4>Transcript</h4>
+          {(r.transcript || []).map((t, i) => (
+            <p key={i}>
+              <strong>{t.role === 'agent' ? 'Agent' : 'Caller'}:</strong> {t.text}
+            </p>
+          ))}
+          <h4>Extracted fields</h4>
+          {(r.extracted_fields || []).length === 0 && <p className="hint">No fields recorded.</p>}
+          <ul>
+            {(r.extracted_fields || []).map((f, i) => (
+              <li key={i}>
+                <code>{f.field_name}</code>: {String(f.field_value)} ({Math.round((f.confidence || 0) * 100)}%)
+              </li>
+            ))}
+          </ul>
+          {r.outcome && (
+            <p>
+              Outcome: <code>{r.outcome}</code>
+            </p>
+          )}
+        </details>
+      ))}
+    </div>
+  );
+}
diff --git a/frontend/src/components/LeadCardForm.jsx b/frontend/src/components/LeadCardForm.jsx
new file mode 100644
index 0000000..f098dec
--- /dev/null
+++ b/frontend/src/components/LeadCardForm.jsx
@@ -0,0 +1,75 @@
+import React from 'react';
+
+export const ABSENT_STUDENT_DEFAULTS = {
+  student_name: '',
+  parent_name: '',
+  class_section: '',
+  absent_date: '',
+};
+
+/** Generic key/value lead card ("who are we calling?").
+ * Props: {value: object, onChange: (next) => void, defaults?: object}
+ */
+export default function LeadCardForm({ value, onChange, defaults }) {
+  const rows = Object.entries(value || {});
+  const set = (next) => onChange(next);
+
+  function updateRow(index, key, val) {
+    const entries = Object.entries(value || {});
+    entries[index] = [key, val];
+    const next = {};
+    for (const [k, v] of entries) {
+      if (String(k).trim()) next[String(k).trim()] = v;
+    }
+    set(next);
+  }
+
+  function removeRow(index) {
+    const entries = Object.entries(value || {});
+    entries.splice(index, 1);
+    set(Object.fromEntries(entries));
+  }
+
+  function addRow() {
+    set({ ...(value || {}), [`field_${rows.length + 1}`]: '' });
+  }
+
+  function loadDefaults() {
+    set({ ...(defaults || {}) });
+  }
+
+  return (
+    <div className="lead-card">
+      {rows.map(([k, v], i) => (
+        <div className="field" key={i}>
+          <input
+            aria-label="Field name"
+            value={k}
+            placeholder="field name"
+            onChange={(e) => updateRow(i, e.target.value, v)}
+          />
+          <input
+            aria-label="Field value"
+            value={v}
+            placeholder="value"
+            onChange={(e) => updateRow(i, k, e.target.value)}
+          />
+          <button type="button" className="btn btn-secondary btn-sm" onClick={() => removeRow(i)}>
+            Remove
+          </button>
+        </div>
+      ))}
+      <div className="form-actions">
+        <button type="button" className="btn btn-secondary btn-sm" onClick={addRow}>
+          Add field
+        </button>
+        {defaults && (
+          <button type="button" className="btn btn-secondary btn-sm" onClick={loadDefaults}>
+            Reset defaults
+          </button>
+        )}
+      </div>
+      <p className="hint">Only non-empty values are sent. The agent uses these names instead of asking who it is calling.</p>
+    </div>
+  );
+}
diff --git a/frontend/src/components/TextPlayground.jsx b/frontend/src/components/TextPlayground.jsx
index c7c8dee..4bdffd4 100644
--- a/frontend/src/components/TextPlayground.jsx
+++ b/frontend/src/components/TextPlayground.jsx
@@ -1,7 +1,8 @@
 import React, { useEffect, useRef, useState } from 'react';
 import { playgroundApi } from '../api.js';
+import LeadCardForm, { ABSENT_STUDENT_DEFAULTS } from './LeadCardForm.jsx';
 
 export function confidenceClass(v) {
   const n = typeof v === 'number' ? v : Number(v);
   if (v == null || Number.isNaN(n)) return '';
   const pct = n <= 1 ? n * 100 : n;
@@ -20,24 +21,31 @@ export function confidenceClass(v) {
  *   versionId      saved agent version to test (number | numeric string)
  *   onFinishReport complete-session result ({call_id, transcript,
  *                  extracted_fields, latency, outcome, ...}) handed to the
  *                  parent for the full-report view / last-run preview.
  *   autoStart      begin the session as soon as versionId is set (default true)
+ *   contact        optional lead-card object passed to startSession; falls back
+ *                  to the card edited in the form below (applies on (re)start).
  */
-export default function TextPlayground({ versionId, onFinishReport, autoStart = true }) {
+export default function TextPlayground({ versionId, onFinishReport, autoStart = true, contact }) {
   const [messages, setMessages] = useState([]); // [{speaker:'caller'|'agent', text}]
   const [input, setInput] = useState('');
   const [busy, setBusy] = useState(false);
   const [error, setError] = useState(null);
   const [done, setDone] = useState(false);
   const [fields, setFields] = useState([]);
   const [completing, setCompleting] = useState(false);
   const [attempt, setAttempt] = useState(0); // bump to retry a failed start
+  const [contactCard, setContactCard] = useState(contact || { ...ABSENT_STUDENT_DEFAULTS });
 
   const sessionRef = useRef(null);
   const logRef = useRef(null);
   const lastReportRef = useRef(null);
+  // Mirror so the (re)start effect always reads the latest card without
+  // restarting the session on every keystroke.
+  const contactRef = useRef(contactCard);
+  contactRef.current = contactCard;
 
   // (Re)start the session whenever the target version changes.
   useEffect(() => {
     lastReportRef.current = null;
     sessionRef.current = null;
@@ -51,11 +59,11 @@ export default function TextPlayground({ versionId, onFinishReport, autoStart =
 
     let cancelled = false;
     setBusy(true);
     (async () => {
       try {
-        const sess = await playgroundApi.startSession(Number(versionId));
+        const sess = await playgroundApi.startSession(Number(versionId), contactRef.current);
         if (cancelled) return;
         sessionRef.current = sess;
         const res = await playgroundApi.sendTurn(sess.call_id, { event: 'start' });
         if (cancelled) return;
         applyTurnResponse(res);
@@ -129,10 +137,14 @@ export default function TextPlayground({ versionId, onFinishReport, autoStart =
     }
   }
 
   return (
     <div className="text-playground">
+      <details className="card" open>
+        <summary>Who are we calling? (optional lead card)</summary>
+        <LeadCardForm value={contactCard} onChange={setContactCard} defaults={ABSENT_STUDENT_DEFAULTS} />
+      </details>
       <div className="form-actions space-between tp-toolbar">
         <span className="meta-line">
           {done ? (
             <span className="text-success">Conversation finished</span>
           ) : busy ? (
diff --git a/frontend/src/pages/CampaignDetailPage.jsx b/frontend/src/pages/CampaignDetailPage.jsx
index 0601170..bbc50a8 100644
--- a/frontend/src/pages/CampaignDetailPage.jsx
+++ b/frontend/src/pages/CampaignDetailPage.jsx
@@ -1,10 +1,11 @@
 import React, { useEffect, useState } from 'react';
 import { Link, useNavigate, useParams } from 'react-router-dom';
-import { api, campaignExportUrl } from '../api.js';
+import { api, campaignExportUrl, playgroundApi } from '../api.js';
 import usePoll from '../hooks/usePoll.js';
 import StatusBadge, { statusLabel } from '../components/StatusBadge.jsx';
+import DryRunReport from '../components/DryRunReport.jsx';
 import Modal from '../components/Modal.jsx';
 import DataTable from '../components/DataTable.jsx';
 import CountsCards from '../components/CountsCards.jsx';
 import ContactImport from '../components/ContactImport.jsx';
 
@@ -182,10 +183,31 @@ export default function CampaignDetailPage() {
   const totalPages = contactsData ? Math.max(1, Math.ceil((contactsData.total || 0) / (contactsData.page_size || PAGE_SIZE))) : 1;
 
   // ---- import ----
   const [importResult, setImportResult] = useState(null);
 
+  // ---- text dry-run (SIMULATION GÇö no calls placed) ----
+  const [dryRunPersona, setDryRunPersona] = useState('');
+  const [dryRunReport, setDryRunReport] = useState(null);
+  const [dryRunBusy, setDryRunBusy] = useState(false);
+  const [dryRunError, setDryRunError] = useState(null);
+
+  async function runDryRun() {
+    setDryRunBusy(true);
+    setDryRunError(null);
+    setDryRunReport(null);
+    try {
+      const body = dryRunPersona ? { persona: dryRunPersona } : {};
+      const report = await playgroundApi.runDryRun(id, body);
+      setDryRunReport(report || null);
+    } catch (e) {
+      setDryRunError(e.message || 'Dry run failed.');
+    } finally {
+      setDryRunBusy(false);
+    }
+  }
+
   function onImported(result) {
     setImportResult(result || {});
     setPage(1);
     refreshContacts();
     reloadDash();
@@ -423,10 +445,33 @@ export default function CampaignDetailPage() {
       {actionError && <div className="banner banner-error">{actionError}</div>}
       {canLaunch && launchBlockedReason && !actionError && (
         <div className="banner banner-info">{launchBlockedReason}</div>
       )}
 
+      <div className="card">
+        <h3 className="page-title">Test campaign (text simulation)</h3>
+        <p className="page-sub">Runs every queued contact against scripted caller personas. No real calls, no minutes.</p>
+        <div className="field">
+          <label htmlFor="dryrun-persona">Persona</label>
+          <select id="dryrun-persona" value={dryRunPersona} onChange={(e) => setDryRunPersona(e.target.value)}>
+            <option value="">Round-robin (all five)</option>
+            <option value="cooperative">Cooperative</option>
+            <option value="terse">Terse</option>
+            <option value="distracted">Distracted</option>
+            <option value="refuses">Refuses</option>
+            <option value="clueless">Clueless</option>
+          </select>
+        </div>
+        {dryRunError && <div className="banner banner-error">{dryRunError}</div>}
+        <div className="form-actions">
+          <button className="btn btn-primary" disabled={dryRunBusy} onClick={runDryRun}>
+            {dryRunBusy ? 'SimulatingGÇª' : 'Run text dry-run'}
+          </button>
+        </div>
+      </div>
+      {dryRunReport && <DryRunReport report={dryRunReport} />}
+
       <div className="tabs">
         <button className={`tab${tab === 'contacts' ? ' active' : ''}`} onClick={() => setTab('contacts')}>
           Contacts
         </button>
         <button className={`tab${tab === 'dashboard' ? ' active' : ''}`} onClick={() => setTab('dashboard')}>
diff --git a/frontend/src/pages/PlaygroundPage.jsx b/frontend/src/pages/PlaygroundPage.jsx
index 75be0af..fba79d3 100644
--- a/frontend/src/pages/PlaygroundPage.jsx
+++ b/frontend/src/pages/PlaygroundPage.jsx
@@ -1,12 +1,14 @@
 import React, { useEffect, useRef, useState } from 'react';
 import { Link, useParams } from 'react-router-dom';
 import { Room, RoomEvent, Track } from 'livekit-client';
-import { agentsApi, playgroundApi } from '../api.js';
-import TranscriptView from '../components/TranscriptView.jsx';
+import { agentsApi, callExportUrl, playgroundApi } from '../api.js';
 import LatencyPanel from '../components/LatencyPanel.jsx';
+import LeadCardForm, { ABSENT_STUDENT_DEFAULTS } from '../components/LeadCardForm.jsx';
 import TextPlayground, { confidenceClass } from '../components/TextPlayground.jsx';
+import { cleanTranscriptText } from '../utils/transcript.js';
+
 
 const PHASES = {
   SETUP: 'setup',
   CONNECTING: 'connecting',
   IN_CALL: 'in_call',
@@ -39,10 +41,11 @@ export default function PlaygroundPage() {
   const [agentsError, setAgentsError] = useState(null);
   const [selectedAgentId, setSelectedAgentId] = useState('');
   const [versions, setVersions] = useState([]);
   const [versionsLoading, setVersionsLoading] = useState(false);
   const [selectedVersionId, setSelectedVersionId] = useState(routeVersionId || '');
+  const [contactCard, setContactCard] = useState({ ...ABSENT_STUDENT_DEFAULTS });
   const [versionInfo, setVersionInfo] = useState(null); // {agentName, version}
   const [infoError, setInfoError] = useState(null);
 
   // ---- live session (voice mode) ----
   const [connectError, setConnectError] = useState(null);
@@ -238,15 +241,16 @@ export default function PlaygroundPage() {
         text = decoded;
       }
     } catch {
       return;
     }
-    if (!text.trim()) return;
+    const cleanText = cleanTranscriptText(text);
+    if (!cleanText) return;
     setCaptions((prev) =>
       [
         ...prev,
-        { speaker: speaker || (participant && participant.identity) || 'agent', text, ts: Date.now() },
+        { speaker: speaker || (participant && participant.identity) || 'agent', text: cleanText, ts: Date.now() },
       ].slice(-200)
     );
   }
 
   async function joinWithSession(sess) {
@@ -328,11 +332,11 @@ export default function PlaygroundPage() {
       return;
     }
 
     let sess;
     try {
-      sess = await playgroundApi.startSession(Number(selectedVersionId));
+      sess = await playgroundApi.startSession(Number(selectedVersionId), contactCard);
       sessionRef.current = sess;
     } catch (e) {
       setConnectError(e.message || 'Could not start a playground session.');
       setPhase(PHASES.SETUP);
       return;
@@ -401,58 +405,52 @@ export default function PlaygroundPage() {
   // The typed-conversation engine (start / turn loop / complete) now lives in
   // components/TextPlayground.jsx GÇö reused here and by the agent workspace.
 
   // ------------------------------------------------------------------ render
 
-  function renderFieldsTable(fields) {
+  function renderLatencySidebar(turns) {
     return (
-      <div className="table-wrap">
-        <table className="data-table">
-          <thead>
-            <tr>
-              <th>Field</th>
-              <th>Value</th>
-              <th style={{ width: '130px' }}>Confidence</th>
-            </tr>
-          </thead>
-          <tbody>
-            {fields.map((f, i) => (
-              <tr key={`${f.field_name}-${i}`}>
-                <td className="cell-strong">{f.field_name}</td>
-                <td>{f.field_value != null ? String(f.field_value) : 'GÇö'}</td>
-                <td>
-                  <span className={`badge ${confidenceClass(f.confidence) || 'badge-gray'}`}>
-                    {f.confidence != null && !Number.isNaN(Number(f.confidence))
-                      ? `${Math.round(
-                          Number(f.confidence) <= 1 ? Number(f.confidence) * 100 : Number(f.confidence)
-                        )}%`
-                      : 'GÇö'}
-                  </span>
-                </td>
-              </tr>
-            ))}
-          </tbody>
-        </table>
+      <div style={{ marginTop: 18 }}>
+        <b style={{ fontSize: 13 }}>Latency</b>
+        <div style={{ marginTop: 8 }}>
+          <LatencyPanel turns={turns} />
+        </div>
       </div>
     );
   }
 
-  if (phase === PHASES.TEXT) {
+  function renderLiveLatencySidebar(turns) {
     return (
-      <div className="narrow-wide">
-        <div className="page-head">
-          <div>
-            <h2 className="page-title">Playground GÇö text mode</h2>
-            <p className="page-sub">
-              Same agent, same conversation flow GÇö typed instead of spoken. Everything is recorded exactly like a
-              voice test.
-            </p>
-          </div>
+      <div style={{ marginTop: 18 }}>
+        <b style={{ fontSize: 13 }}>
+          Latency <span style={{ color: 'var(--dim)', fontWeight: 400 }}>-+ live</span>
+        </b>
+        <div style={{ marginTop: 8 }}>
+          <LatencyPanel turns={turns} />
         </div>
+      </div>
+    );
+  }
 
-        <div className="card chat-panel">
-          <div className="form-actions space-between" style={{ marginBottom: 12 }}>
+  if (phase === PHASES.TEXT) {
+    return (
+      <div className="pg">
+        <div className="card" style={{ padding: '20px 24px' }}>
+          <div className="card-h" style={{ marginBottom: 0 }}>
+            <h3>Text mode -+ same extraction pipeline</h3>
+            <span className="chip queued"><i></i>sandbox</span>
+          </div>
+          <TextPlayground
+            key={selectedVersionId}
+            versionId={selectedVersionId}
+            contact={contactCard}
+            onFinishReport={(res) => {
+              setResult(res || {});
+              setPhase(PHASES.ENDED);
+            }}
+          />
+          <div className="form-actions space-between" style={{ marginTop: 12 }}>
             <span className="meta-line">
               {versionInfo && (
                 <>
                   <span>
                     <strong>Agent:</strong> {versionInfo.agentName || '(unknown)'}
@@ -465,342 +463,445 @@ export default function PlaygroundPage() {
             </span>
             <button type="button" className="btn btn-secondary btn-sm" onClick={backToSetup}>
               Back to setup
             </button>
           </div>
-
-          <TextPlayground
-            key={selectedVersionId}
-            versionId={selectedVersionId}
-            onFinishReport={(res) => {
-              setResult(res || {});
-              setPhase(PHASES.ENDED); // reuse the full voice-mode report view
-            }}
-          />
         </div>
+        <aside className="card pad">
+          <b style={{ fontSize: 13 }}>
+            Extracted fields <span style={{ color: 'var(--dim)', fontWeight: 400 }}>-+ live</span>
+          </b>
+          <div style={{ marginTop: 8 }}>
+            <p className="hint">Start a session to watch fields fill in real time.</p>
+          </div>
+        </aside>
       </div>
     );
   }
 
   if (phase === PHASES.IN_CALL || phase === PHASES.CONNECTING) {
     const connecting = phase === PHASES.CONNECTING;
     const speaking = micLevel > MIC_SPEAK_THRESHOLD;
+    const orbState = connecting ? 'listening' : speaking ? 'speaking' : bargeIn ? 'interrupted' : 'listening';
+    const isLive = !connecting;
+    const agentFields = (result && result.extracted_fields) || [];
+    const agentTurns = (result && result.transcript) || [];
     return (
-      <div className="playground-live">
-        <div className="card playground-console">
-          <div className="playground-status">
-            <div className="playground-timer" aria-label={`Call duration ${fmtClock(elapsedMs)}`}>
+      <div className="pg">
+        <div className="card" style={{ padding: '10px 26px 26px' }}>
+          <div className="card-h">
+            <h3>{versionInfo ? `${versionInfo.agentName || 'Unknown'} -+ live session` : 'Live session'}</h3>
+            <span className={`chip in-progress`} id="stateChip">
+              <i></i>{connecting ? 'ConnectingGÇª' : speaking ? 'Listening' : bargeIn ? 'Interrupted' : 'Agent on the line'}
+            </span>
+          </div>
+          <div className="orb-wrap">
+            <button className={`big-orb${isLive ? ' live' : ''}`} data-m={orbState} aria-label="Session orb">
+              <svg width="44" height="44" viewBox="0 0 24 24" fill="none">
+                <rect x="9" y="3" width="6" height="11" rx="3" fill="#e9e4da" />
+                <path d="M5 11a7 7 0 0 0 14 0M12 18v3" stroke="#e9e4da" strokeWidth="1.6" strokeLinecap="round" />
+              </svg>
+            </button>
+            <span className="mono" style={{ fontSize: 12, color: 'var(--dim)' }}>
               {fmtClock(elapsedMs)}
-            </div>
-            {connecting ? (
-              <span className="live-indicator big">
-                <span className="spinner spinner-inline" /> ConnectingGÇª
-              </span>
+            </span>
+          </div>
+          <div className="caps">
+            {captions.length === 0 ? (
+              <p className="hint" style={{ alignSelf: 'center' }}>
+                {connecting ? 'ConnectingGÇª' : 'Waiting for captionsGÇª'}
+              </p>
             ) : (
-              <span className={`live-indicator big${speaking ? ' speaking' : ''}`}>
-                <span className="live-dot" /> {speaking ? 'ListeningGÇª' : 'Agent on the line'}
-              </span>
-            )}
-            {bargeIn && (
-              <span className="badge badge-orange barge-badge" title="You spoke while the agent was talking">
-                Barge-in detected
-              </span>
+              captions.slice(-8).map((cap, i) => {
+                const isAgent = ['agent', 'ai', 'bot', 'assistant', 'system', 'voice_agent'].includes(
+                  String(cap.speaker || '').toLowerCase()
+                );
+                return (
+                  <div key={`${cap.ts}-${i}`} className={`cap-bub ${isAgent ? 'agent' : 'caller'}`}>
+                    <span className="cap-who">{isAgent ? 'Agent' : 'Caller'}</span>
+                    {cap.text}
+                  </div>
+                );
+              })
             )}
           </div>
-
-          <div className="playground-meter" aria-hidden="true">
-            <div className="playground-meter-fill" style={{ width: `${Math.min(100, micLevel * 160)}%` }} />
-          </div>
-
-          <p className="hint">
-            Talk naturally GÇö you can interrupt the agent mid-sentence and it will stop and listen. Press{' '}
-            <strong>End call</strong> when done; the transcript and results appear right after.
-          </p>
-
-          <div className="form-actions">
-            <button type="button" className="btn btn-danger btn-lg" onClick={endCall} disabled={connecting}>
+          <div className="form-actions" style={{ justifyContent: 'flex-end', marginTop: 14 }}>
+            <button type="button" className="btn btn-danger btn-sm" onClick={endCall} disabled={connecting}>
               End call
             </button>
           </div>
         </div>
 
         {statusNote && <div className="banner banner-info">{statusNote}</div>}
 
-        <div className="card">
-          <h3 className="card-title">Live captions</h3>
-          {captions.length === 0 ? (
-            <p className="hint">Waiting for captionsGÇª (they stream in here as the conversation progresses)</p>
-          ) : (
-            <TranscriptView turns={captions.slice(-8)} emptyText="No captions." />
-          )}
-        </div>
+        <aside className="card pad">
+          <b style={{ fontSize: 13 }}>
+            Extracted fields <span style={{ color: 'var(--dim)', fontWeight: 400 }}>-+ live</span>
+          </b>
+          <div style={{ marginTop: 8 }}>
+            {agentFields.map((f, i) => (
+              <div key={`${f.field_name}-${i}`} className="frow2">
+                <span className="k">{f.field_name}</span>
+                <span>
+                  {f.field_value != null ? String(f.field_value) : 'GÇö not captured yet'}{' '}
+                  <span className={`confchip ${confidenceClass(f.confidence)}`}>
+                    {f.confidence != null && !Number.isNaN(Number(f.confidence))
+                      ? `${Math.round(
+                          Number(f.confidence) <= 1 ? Number(f.confidence) * 100 : Number(f.confidence)
+                        )}%`
+                      : ''}
+                  </span>
+                </span>
+              </div>
+            ))}
+          </div>
+          {renderLiveLatencySidebar(agentTurns)}
+        </aside>
       </div>
     );
   }
 
   if (phase === PHASES.ENDED) {
     const turns = (result && result.transcript) || [];
     const fields = (result && result.extracted_fields) || [];
+    const resolvedCallId = result && (result.call_id || (sessionRef.current && sessionRef.current.call_id));
     return (
-      <div className="stack">
-        <button type="button" className="btn btn-ghost self-start" onClick={backToSetup}>
-          GåÉ Run another test
-        </button>
-
-        <div className="banner banner-success">
-          <strong>Call finished.</strong>{' '}
-          {result && result.duration_seconds != null && <>Duration: {fmtClock(result.duration_seconds * 1000)}. </>}
-          {result && result.flagged_for_human ? 'This session was flagged for human review.' : null}
-        </div>
-
-        {completeError && (
-          <div className="banner banner-error">
-            {completeError}{' '}
-            <button type="button" className="btn btn-secondary btn-sm" onClick={completeSession} disabled={completing}>
-              {completing ? 'RetryingGÇª' : 'Retry'}
-            </button>
-          </div>
-        )}
-
-        {!result && !completeError && (
-          <div className="loading-page">
-            <span className="spinner" /> Collecting transcript and resultsGÇª
+      <div className="pg">
+        <div className="card" style={{ padding: '24px' }}>
+          <button type="button" className="btn btn-ghost self-start" onClick={backToSetup}>
+            GåÉ Run another test
+          </button>
+
+          <div className="banner banner-success" style={{ marginTop: 12 }}>
+            <strong>Call finished.</strong>{' '}
+            {result && result.duration_seconds != null && <>Duration: {fmtClock(result.duration_seconds * 1000)}. </>}
+            {result && result.flagged_for_human ? 'This session was flagged for human review.' : null}
           </div>
-        )}
 
-        {result && (
-          <>
-            <div className="card">
-              <h3 className="card-title">Extracted fields</h3>
-              {fields.length === 0 ? (
-                <p className="hint">No structured fields were extracted during this call.</p>
-              ) : (
-                renderFieldsTable(fields)
-              )}
-              {result.outcome ? (
-                <p className="hint">
-                  Outcome: <span className="chip">{String(result.outcome)}</span>
-                </p>
-              ) : null}
+          {completeError && (
+            <div className="banner banner-error" style={{ marginTop: 12 }}>
+              {completeError}{' '}
+              <button type="button" className="btn btn-secondary btn-sm" onClick={completeSession} disabled={completing}>
+                {completing ? 'RetryingGÇª' : 'Retry'}
+              </button>
             </div>
+          )}
 
-            <div className="card">
-              <h3 className="card-title">Latency</h3>
-              <LatencyPanel turns={turns} summary={result.latency} />
+          {!result && !completeError && (
+            <div className="loading-page" style={{ marginTop: 20 }}>
+              <span className="spinner" /> Collecting transcript and resultsGÇª
             </div>
+          )}
 
-            <div className="card">
-              <h3 className="card-title">Transcript</h3>
-              <TranscriptView turns={turns} emptyText="No transcript was recorded for this session." />
-            </div>
+          {result && (
+            <>
+              <div style={{ marginTop: 20 }}>
+                <h3 className="card-title">Transcript</h3>
+                {turns.length === 0 ? (
+                  <p className="hint">No transcript was recorded for this session.</p>
+                ) : (
+                  <div className="transcript" aria-live="polite">
+                    {turns.map((t, i) => {
+                      const isAgent = ['agent', 'ai', 'bot', 'assistant', 'system', 'voice_agent'].includes(
+                        String(t.speaker || '').toLowerCase()
+                      );
+                      const displayName = isAgent
+                        ? 'Agent'
+                        : t.speaker
+                          ? String(t.speaker)
+                            .replace(/[_-]+/g, ' ')
+                            .replace(/\b\w/g, (ch) => ch.toUpperCase())
+                          : 'Caller';
+                      return (
+                        <div key={t.turn_index != null ? `turn-${t.turn_index}` : `i-${i}`} className={`cap-bub ${isAgent ? 'agent' : 'caller'}`}>
+                          <span className="cap-who">{displayName}</span>
+                          {cleanTranscriptText(t.text)}
+                        </div>
+                      );
+                    })}
+                  </div>
+                )}
+              </div>
+
+              {result.outcome && (
+                <p className="hint" style={{ marginTop: 12 }}>
+                  Outcome: <span className="chip">{String(result.outcome)}</span>
+                </p>
+              )}
+
+              {versionInfo && versionInfo.agentName && (
+                <p className="hint" style={{ marginTop: 12 }}>
+                  Tested <strong>{versionInfo.agentName}</strong> v{versionInfo.version}.{' '}
+                  <Link to="/agents">Back to agents</Link> -+ <Link to="/campaigns">Launch this agent as a campaign</Link>
+                </p>
+              )}
+            </>
+          )}
+        </div>
 
-            {versionInfo && versionInfo.agentName && (
+        <aside className="card pad">
+          <b style={{ fontSize: 13 }}>Extracted fields</b>
+          <div style={{ marginTop: 8 }}>
+            {fields.length === 0 ? (
               <p className="hint">
-                Tested <strong>{versionInfo.agentName}</strong> v{versionInfo.version}.{' '}
-                <Link to="/agents">Back to agents</Link> -+ <Link to="/campaigns">Launch this agent as a campaign</Link>
+                No structured fields were extracted during this call. The agent collects fields during calls; check the
+                transcript for what it asked.
               </p>
+            ) : (
+              fields.map((f, i) => (
+                <div key={`${f.field_name}-${i}`} className="frow2">
+                  <span className="k">{f.field_name}</span>
+                  <span>
+                    {f.field_value != null ? String(f.field_value) : 'GÇö'}{' '}
+                    <span className={`confchip ${confidenceClass(f.confidence)}`}>
+                      {f.confidence != null && !Number.isNaN(Number(f.confidence))
+                        ? `${Math.round(
+                            Number(f.confidence) <= 1 ? Number(f.confidence) * 100 : Number(f.confidence)
+                          )}%`
+                        : ''}
+                    </span>
+                  </span>
+                </div>
+              ))
             )}
-          </>
-        )}
+          </div>
+          <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
+            {resolvedCallId && (
+              <>
+                <button
+                  type="button"
+                  className="btn btn-secondary btn-sm"
+                  onClick={() => window.open(callExportUrl(resolvedCallId, 'csv'), '_blank')}
+                >
+                  Export CSV
+                </button>
+                <button
+                  type="button"
+                  className="btn btn-secondary btn-sm"
+                  onClick={() => window.open(callExportUrl(resolvedCallId, 'xlsx'), '_blank')}
+                >
+                  Export XLSX
+                </button>
+              </>
+            )}
+          </div>
+          {renderLatencySidebar(turns)}
+        </aside>
       </div>
     );
   }
 
   // ------------------------------------------------------------------ setup
 
   return (
-    <div className="narrow-wide">
-      <div className="page-head">
-        <div>
-          <h2 className="page-title">Playground</h2>
-          <p className="page-sub">
-            Test any saved agent version straight from this browser GÇö speak over your microphone or type in Text mode.
-            Nothing is dialed, so it costs zero telephony minutes.
-          </p>
+    <div className="pg">
+      <div className="card" style={{ padding: '24px' }}>
+        <div className="card-h">
+          <h3>Set up a test session</h3>
+          <span style={{ fontSize: 12, color: 'var(--dim)' }}>sandbox</span>
         </div>
-      </div>
 
-      {fatalError ? (
-        <div className="stack">
-          <div className="banner banner-error">{fatalError}</div>
-          <div className="card">
-            <div className="form-actions">
+        {fatalError && (
+          <div style={{ marginTop: 20 }}>
+            <div className="banner banner-error">{fatalError}</div>
+            <div className="form-actions" style={{ marginTop: 12 }}>
               <button type="button" className="btn btn-primary" onClick={backToSetup}>
                 Back to setup
               </button>
             </div>
           </div>
-        </div>
-      ) : (
-        <div className="stack">
-          <div className="tab-row" role="tablist" aria-label="Test mode">
-            <button
-              type="button"
-              role="tab"
-              aria-selected={mode === MODES.VOICE}
-              className={`tab-btn${mode === MODES.VOICE ? ' active' : ''}`}
-              onClick={() => {
-                setMode(MODES.VOICE);
-                setConnectError(null);
-              }}
-            >
-              Voice (mic)
-            </button>
-            <button
-              type="button"
-              role="tab"
-              aria-selected={mode === MODES.TEXT}
-              className={`tab-btn${mode === MODES.TEXT ? ' active' : ''}`}
-              onClick={() => {
-                setMode(MODES.TEXT);
-                setConnectError(null);
-              }}
-            >
-              Text
-            </button>
-          </div>
+        )}
 
-          {!routeVersionId && (
-            <div className="card">
-              <h3 className="card-title">Choose what to test</h3>
-              {agentsError && (
-                <div className="banner banner-error">
-                  {agentsError}{' '}
-                  <Link to="/agents/new" className="btn btn-secondary btn-sm">
-                    Create an agent
-                  </Link>
-                </div>
-              )}
-              {!agentsError && agents && agents.length === 0 && (
-                <div className="empty-state">
-                  No agents yet GÇö build one first.
-                  <div className="form-actions">
-                    <Link to="/agents/new" className="btn btn-primary">
-                      + New Agent
+        {!fatalError && (
+          <div style={{ marginTop: 20 }}>
+            <div className="mode-toggle">
+              <button
+                type="button"
+                className={mode === MODES.VOICE ? 'on' : ''}
+                onClick={() => {
+                  setMode(MODES.VOICE);
+                  setConnectError(null);
+                }}
+              >
+                Voice session
+              </button>
+              <button
+                type="button"
+                className={mode === MODES.TEXT ? 'on' : ''}
+                onClick={() => {
+                  setMode(MODES.TEXT);
+                  setConnectError(null);
+                }}
+              >
+                Text mode
+              </button>
+            </div>
+
+            {!routeVersionId && (
+              <div style={{ marginTop: 20 }}>
+                {agentsError && (
+                  <div className="banner banner-error">
+                    {agentsError}{' '}
+                    <Link to="/agents/new" className="btn btn-secondary btn-sm">
+                      Create an agent
                     </Link>
                   </div>
-                </div>
-              )}
-              {!agentsError && agents && agents.length > 0 && (
-                <div className="picker-row">
-                  <div className="field">
-                    <label htmlFor="pg-agent">Agent</label>
-                    <select
-                      id="pg-agent"
-                      value={selectedAgentId}
-                      onChange={(e) => setSelectedAgentId(e.target.value)}
-                    >
-                      {agents.map((a) => (
-                        <option key={a.id} value={a.id}>
-                          {a.name}
-                        </option>
-                      ))}
-                    </select>
+                )}
+                {!agentsError && agents && agents.length === 0 && (
+                  <div className="empty-state">
+                    No agents yet GÇö build one first.
+                    <div className="form-actions">
+                      <Link to="/agents/new" className="btn btn-primary">
+                        + New Agent
+                      </Link>
+                    </div>
                   </div>
-                  <div className="field">
-                    <label htmlFor="pg-version">Version</label>
-                    <select
-                      id="pg-version"
-                      value={selectedVersionId}
-                      onChange={(e) => setSelectedVersionId(e.target.value)}
-                      disabled={versionsLoading}
-                    >
-                      {versionsLoading && <option>LoadingGÇª</option>}
-                      {!versionsLoading &&
-                        versions.map((v) => (
-                          <option key={v.id} value={v.id}>
-                            v{v.version} GÇö saved {new Date(v.created_at).toLocaleString()}
+                )}
+                {!agentsError && agents && agents.length > 0 && (
+                  <>
+                    <div className="fieldrow" style={{ marginTop: 12 }}>
+                      <label>Agent</label>
+                      <select
+                        value={selectedAgentId}
+                        onChange={(e) => setSelectedAgentId(e.target.value)}
+                      >
+                        {agents.map((a) => (
+                          <option key={a.id} value={a.id}>
+                            {a.name}
                           </option>
                         ))}
-                      {!versionsLoading && versions.length === 0 && <option value="">No saved versions yet</option>}
-                    </select>
-                  </div>
-                </div>
-              )}
-              {infoError && <p className="hint hint-error">{infoError}</p>}
-            </div>
-          )}
-
-          {selectedVersionId && mode === MODES.VOICE && (
-            <>
-              <div className="card">
-                <h3 className="card-title">Before you start</h3>
-                <p>
+                      </select>
+                    </div>
+                    <div className="fieldrow" style={{ marginTop: 8 }}>
+                      <label>Version</label>
+                      <select
+                        value={selectedVersionId}
+                        onChange={(e) => setSelectedVersionId(e.target.value)}
+                        disabled={versionsLoading}
+                      >
+                        {versionsLoading && <option>LoadingGÇª</option>}
+                        {!versionsLoading &&
+                          versions.map((v) => (
+                            <option key={v.id} value={v.id}>
+                              v{v.version} GÇö saved {new Date(v.created_at).toLocaleString()}
+                            </option>
+                          ))}
+                        {!versionsLoading && versions.length === 0 && <option value="">No saved versions yet</option>}
+                      </select>
+                    </div>
+                  </>
+                )}
+                {infoError && <p className="hint hint-error" style={{ marginTop: 8 }}>{infoError}</p>}
+              </div>
+            )}
+            <details className="card" open style={{ marginTop: 12 }}>
+              <summary>Who are we calling? (optional lead card)</summary>
+              <LeadCardForm value={contactCard} onChange={setContactCard} defaults={ABSENT_STUDENT_DEFAULTS} />
+            </details>
+
+            {selectedVersionId && mode === MODES.VOICE && (
+              <div style={{ marginTop: 20 }}>
+                <p style={{ fontSize: 13.5, lineHeight: 1.6 }}>
                   Your browser will ask for microphone permission GÇö this is required so the agent can hear you. Audio
                   plays through your speakers or headset, exactly like a phone call. The whole conversation is recorded
                   as a test session you can review afterwards.
                 </p>
                 <p className="hint">
                   Tip: use headphones to avoid echo. If nothing seems to happen, check that the correct microphone is
                   selected in your browser's site settings.
                 </p>
               </div>
-              <div className="card">
-                <h3 className="card-title">Ready to talk</h3>
-                {versionInfo ? (
-                  <p className="meta-line">
-                    <span>
-                      <strong>Agent:</strong> {versionInfo.agentName || '(unknown)'}
-                    </span>
-                    <span>
-                      <strong>Version:</strong> v{versionInfo.version}
-                    </span>
-                  </p>
-                ) : (
-                  <p className="hint">Loading version detailsGÇª</p>
-                )}
-                {connectError && <div className="banner banner-error">{connectError}</div>}
-                <div className="form-actions">
-                  <button
-                    type="button"
-                    className="btn btn-primary btn-lg"
-                    onClick={startCall}
-                    disabled={phase === PHASES.CONNECTING || !selectedVersionId}
-                  >
-                    {phase === PHASES.CONNECTING ? 'ConnectingGÇª' : 'Enable microphone & start call'}
-                  </button>
-                </div>
-              </div>
-            </>
-          )}
+            )}
 
-          {selectedVersionId && mode === MODES.TEXT && (
-            <div className="card">
-              <h3 className="card-title">Ready to chat</h3>
-              {versionInfo ? (
-                <p className="meta-line">
-                  <span>
-                    <strong>Agent:</strong> {versionInfo.agentName || '(unknown)'}
-                  </span>
-                  <span>
-                    <strong>Version:</strong> v{versionInfo.version}
-                  </span>
+            {selectedVersionId && mode === MODES.TEXT && (
+              <div style={{ marginTop: 20 }}>
+                <p className="hint">
+                  No microphone or voice room needed. The agent opens with its disclosure and first question; reply by
+                  typing. Extraction and the final report work exactly like a voice test.
                 </p>
-              ) : (
-                <p className="hint">Loading version detailsGÇª</p>
-              )}
-              <p className="hint">
-                No microphone or voice room needed. The agent opens with its disclosure and first question; reply by
-                typing. Extraction and the final report work exactly like a voice test.
-              </p>
-              {connectError && <div className="banner banner-error">{connectError}</div>}
-              <div className="form-actions">
-                <button
-                  type="button"
-                  className="btn btn-primary btn-lg"
-                  onClick={() => {
-                    setResult(null);
-                    setFatalError(null);
-                    setConnectError(null);
-                    setPhase(PHASES.TEXT);
-                  }}
-                >
-                  Start text test call
-                </button>
               </div>
-            </div>
-          )}
+            )}
+
+            {selectedVersionId && (
+              <div style={{ display: 'flex', gap: 12, marginTop: 26 }}>
+                {mode === MODES.VOICE && (
+                  <>
+                    {versionInfo && (
+                      <span className="meta-line" style={{ alignSelf: 'center', fontSize: 13 }}>
+                        <strong>Agent:</strong> {versionInfo.agentName || '(unknown)'} -+ v{versionInfo.version}
+                      </span>
+                    )}
+                    {connectError && <div className="banner banner-error" style={{ width: '100%' }}>{connectError}</div>}
+                    <button
+                      type="button"
+                      className="btn btn-primary"
+                      style={{ padding: '13px 26px' }}
+                      onClick={startCall}
+                      disabled={phase === PHASES.CONNECTING || !selectedVersionId}
+                    >
+                      {phase === PHASES.CONNECTING ? 'ConnectingGÇª' : 'Start Voice Session'}
+                    </button>
+                    <button
+                      type="button"
+                      className="btn btn-ghost"
+                      onClick={() => {
+                        setResult(null);
+                        setFatalError(null);
+                        setConnectError(null);
+                        setPhase(PHASES.TEXT);
+                      }}
+                    >
+                      Start in Text Mode
+                    </button>
+                  </>
+                )}
+                {mode === MODES.TEXT && (
+                  <>
+                    {versionInfo && (
+                      <span className="meta-line" style={{ alignSelf: 'center', fontSize: 13 }}>
+                        <strong>Agent:</strong> {versionInfo.agentName || '(unknown)'} -+ v{versionInfo.version}
+                      </span>
+                    )}
+                    {connectError && <div className="banner banner-error" style={{ width: '100%' }}>{connectError}</div>}
+                    <button
+                      type="button"
+                      className="btn btn-primary"
+                      style={{ padding: '13px 26px' }}
+                      onClick={() => {
+                        setResult(null);
+                        setFatalError(null);
+                        setConnectError(null);
+                        setPhase(PHASES.TEXT);
+                      }}
+                    >
+                      Start in Text Mode
+                    </button>
+                    <button
+                      type="button"
+                      className="btn btn-ghost"
+                      onClick={() => {
+                        setMode(MODES.VOICE);
+                        setConnectError(null);
+                      }}
+                    >
+                      Voice Session
+                    </button>
+                  </>
+                )}
+              </div>
+            )}
+          </div>
+        )}
+      </div>
+
+      <aside className="card pad">
+        <b style={{ fontSize: 13 }}>
+          Extracted fields <span style={{ color: 'var(--dim)', fontWeight: 400 }}>-+ live</span>
+        </b>
+        <div style={{ marginTop: 8 }}>
+          <p className="hint">Start a session to watch fields fill in real time.</p>
         </div>
-      )}
+        <div style={{ marginTop: 18 }} />
+      </aside>
     </div>
   );
 }
diff --git a/frontend/src/pages/TestCallPage.jsx b/frontend/src/pages/TestCallPage.jsx
index 4f4742b..a8133a4 100644
--- a/frontend/src/pages/TestCallPage.jsx
+++ b/frontend/src/pages/TestCallPage.jsx
@@ -1,39 +1,69 @@
 import React, { useEffect, useState } from 'react';
 import { Link } from 'react-router-dom';
-import { api } from '../api.js';
+import { agentsApi, api } from '../api.js';
+import LeadCardForm, { ABSENT_STUDENT_DEFAULTS } from '../components/LeadCardForm.jsx';
 import StatusBadge from '../components/StatusBadge.jsx';
 
 export default function TestCallPage() {
   const [domains, setDomains] = useState([]);
   const [domainsError, setDomainsError] = useState(null);
   const [domainId, setDomainId] = useState('');
+  const [agents, setAgents] = useState([]);
+  const [agentId, setAgentId] = useState('');
+  const [versions, setVersions] = useState([]);
+  const [versionId, setVersionId] = useState('');
+  const [contactCard, setContactCard] = useState({ ...ABSENT_STUDENT_DEFAULTS });
   const [to, setTo] = useState('');
   const [busy, setBusy] = useState(false);
   const [error, setError] = useState(null);
   const [result, setResult] = useState(null);
+  const [placedWith, setPlacedWith] = useState(null);
 
   useEffect(() => {
-    api
-      .listDomainConfigs()
-      .then((list) => {
-        setDomains(Array.isArray(list) ? list : []);
-        setDomainsError(null);
-      })
-      .catch((e) => setDomainsError(e.message));
+    api.listDomainConfigs().then((list) => {
+      setDomains(Array.isArray(list) ? list : []);
+      setDomainsError(null);
+    }).catch((e) => setDomainsError(e.message));
+    agentsApi.list().then((list) => {
+      setAgents(Array.isArray(list) ? list : []);
+    }).catch(() => setAgents([]));
   }, []);
 
+  useEffect(() => {
+    if (!agentId) {
+      setVersions([]);
+      setVersionId('');
+      return;
+    }
+    agentsApi.listVersions(agentId).then((list) => {
+      const arr = Array.isArray(list) ? list : [];
+      setVersions(arr);
+      setVersionId(arr.length ? String(arr[arr.length - 1].id) : '');
+    }).catch(() => {
+      setVersions([]);
+      setVersionId('');
+    });
+  }, [agentId]);
+
   async function placeCall() {
     setBusy(true);
     setError(null);
     setResult(null);
-    const payload = { domain_config_id: domainId };
+    const payload = {};
+    if (domainId) payload.domain_config_id = Number(domainId);
+    if (versionId) payload.agent_version_id = Number(versionId);
+    const card = Object.fromEntries(
+      Object.entries(contactCard || {}).filter(([, v]) => String(v || '').trim())
+    );
+    if (Object.keys(card).length) payload.contact = card;
     const trimmed = to.trim();
     if (trimmed) payload.to = trimmed;
     try {
       const res = await api.placeTestCall(payload);
       setResult(res || {});
+      setPlacedWith(versionId ? `agent version ${versionId}` : 'latest agent version');
     } catch (e) {
       setError(e.message || 'Could not place test call.');
     } finally {
       setBusy(false);
     }
@@ -50,11 +80,11 @@ export default function TestCallPage() {
         </div>
       </div>
 
       <div className="card">
         <div className="field">
-          <label htmlFor="tc-domain">Call domain</label>
+          <label htmlFor="tc-domain">Call domain (optional GÇö derived from the agent version when blank)</label>
           <select id="tc-domain" value={domainId} onChange={(e) => setDomainId(e.target.value)}>
             <option value="">Select a call domainGÇª</option>
             {domains.map((d) => (
               <option key={d.id} value={d.id}>
                 {d.display_name || d.name}
@@ -66,10 +96,44 @@ export default function TestCallPage() {
           {!domainsError && domains.length === 0 && (
             <p className="hint">No domain configs available yet GÇö add one first (see /domain-configs).</p>
           )}
         </div>
 
+        <div className="field">
+          <label htmlFor="tc-agent">Agent</label>
+          <select id="tc-agent" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
+            <option value="">Select an agentGÇª</option>
+            {agents.map((a) => (
+              <option key={a.id} value={a.id}>
+                {a.name}
+              </option>
+            ))}
+          </select>
+        </div>
+
+        <div className="field">
+          <label htmlFor="tc-version">Agent version</label>
+          <select
+            id="tc-version"
+            value={versionId}
+            onChange={(e) => setVersionId(e.target.value)}
+            disabled={!agentId}
+          >
+            <option value="">{agentId ? 'Latest version' : 'Pick an agent firstGÇª'}</option>
+            {versions.map((v) => (
+              <option key={v.id} value={v.id}>
+                v{v.version} GÇö saved {v.created_at ? new Date(v.created_at).toLocaleString() : `#${v.id}`}
+              </option>
+            ))}
+          </select>
+        </div>
+
+        <details className="card" open>
+          <summary>Who are we calling? (optional lead card)</summary>
+          <LeadCardForm value={contactCard} onChange={setContactCard} defaults={ABSENT_STUDENT_DEFAULTS} />
+        </details>
+
         <div className="field">
           <label htmlFor="tc-to">Call destination (optional)</label>
           <input
             id="tc-to"
             type="tel"
@@ -83,18 +147,19 @@ export default function TestCallPage() {
         </div>
 
         {error && <div className="banner banner-error">{error}</div>}
 
         <div className="form-actions">
-          <button className="btn btn-primary" disabled={busy || !domainId} onClick={placeCall}>
+          <button className="btn btn-primary" disabled={busy || !(domainId || versionId)} onClick={placeCall}>
             {busy ? 'Placing callGÇª' : 'Place test call'}
           </button>
         </div>
 
         {result && (
           <div className="banner banner-success">
             <strong>Test call placed.</strong>
+            {placedWith && <span> Placed with {placedWith}.</span>}
             <div className="result-grid">
               <span>
                 Status: <StatusBadge status={result.status} />
               </span>
               {result.call_id != null && (
diff --git a/voice-agent/app/pipeline.py b/voice-agent/app/pipeline.py
index 4d9ad53..0d824ee 100644
--- a/voice-agent/app/pipeline.py
+++ b/voice-agent/app/pipeline.py
@@ -43,11 +43,11 @@ from app.extraction_tools import (
     LOW_CONFIDENCE_THRESHOLD,
     MAX_ASKS_PER_FIELD,
     ExtractionCoordinator,
     VoiceAgentTools,
 )
-from app.prompting import render_system_prompt
+from app.prompting import build_opening_line, build_token_map, render_system_prompt, scrub_speech_text
 
 logger = logging.getLogger("voice_agent.pipeline")
 
 PLAYGROUND_PREFIX = "playground-"
 APOLOGY_TEXT = (
@@ -144,14 +144,16 @@ def build_providers(
             (voice_settings or {}).get("stt_language", "en")
         ).strip().lower() or "en"
         # P0-1 endpointing tuning: the livekit-plugins-deepgram 1.7.0 kwarg is
         # ``endpointing_ms`` (introspected signature has NO ``endpointing``);
         # plugin default is a hair-trigger 25 ms which fragments speech.
+        # 300ms (echo hardening): the agent's own looped-back TTS audio must
+        # not hair-trigger a retrigger at the old 200ms.
         bundle.stt = deepgram.STT(
             model="nova-3",
             language=stt_lang,
-            endpointing_ms=200,
+            endpointing_ms=300,
             api_key=settings.deepgram_api_key,
         )
     else:
         bundle.problems.append(
             "DEEPGRAM_API_KEY missing - speech-to-text disabled"
@@ -320,12 +322,21 @@ class TurnTelemetry:
 
     def _on_conversation_item_added(self, ev: Any) -> None:
         item = getattr(ev, "item", None)
         if item is None:
             return
+        # Only real assistant MESSAGE items carry spoken text. Function calls
+        # and tool results (item.type in {"function_call", "tool_call", ...})
+        # must never enter captions/_agent_text/transcript (B).
+        item_type = str(getattr(item, "type", "") or "").lower()
+        if item_type and item_type not in {"message", "assistant_message", "text"}:
+            return
+        tool_calls = getattr(item, "tool_calls", None)
+        if tool_calls:
+            return
         role = str(getattr(item, "role", "")).lower()
-        text = str(getattr(item, "text_content", "") or "").strip()
+        text = scrub_speech_text(getattr(item, "text_content", ""))
         if role == "assistant" and text:
             if not self._got_agent_item and self._llm_first_token_ms is None and self._reply_start_at is not None:
                 # APPROXIMATION fallback: item commit time - reply start upper-
                 # bounds true TTFT; used only if llm_metrics never arrived.
                 self._llm_first_token_ms = (
@@ -592,10 +603,28 @@ def _required_fields_from_schema(config: Mapping[str, Any]) -> frozenset[str]:
                 if validation == "required":
                     required.add(str(name))
     return frozenset(required)
 
 
+async def _speak_opening(
+    session: Any,
+    config: Mapping[str, Any],
+    tokens: Mapping[str, str],
+    contact: Optional[Mapping[str, Any]],
+) -> bool:
+    """Speak the composed opening with interruptions disabled.
+
+    Returns True when spoken; False (fall back to the prompt-driven
+    auto-turn) when there is no disclosure script to anchor it.
+    """
+    opening = build_opening_line(config, tokens, contact)
+    if not opening:
+        return False
+    await session.say(opening, allow_interruptions=False)
+    return True
+
+
 async def run_session(ctx: JobContext, settings: Settings) -> None:
     """Full lifecycle for one accepted playground job. Never raises."""
     room_name = ctx.room.name or ""
     backend = BackendClient(settings.backend_internal_url, settings.internal_api_token)
     parsed: Optional[ParsedJob] = parse_room_metadata(_room_metadata(ctx))
@@ -655,21 +684,30 @@ async def run_session(ctx: JobContext, settings: Settings) -> None:
             )
             return
         assert bundle.stt is not None and bundle.llm is not None
         assert bundle.tts is not None
 
-        instructions = render_system_prompt(config, contact=parsed.contact)
+        # Fetch per-call context (institution_name + contact) once at session
+        # start; {} on failure is fine GÇö tokens resolve to empty and are dropped.
+        call_context = await backend.fetch_call_context(call_id)
+        instructions = render_system_prompt(
+            config,
+            contact=parsed.contact,
+            tokens=build_token_map(contact=parsed.contact, context=call_context),
+        )
+        schema = config.get("extraction_schema") or {}
         coordinator = ExtractionCoordinator(
             required_fields=_required_fields_from_schema(config),
             low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD,
             max_asks_per_field=MAX_ASKS_PER_FIELD,
+            schema=schema,
         )
         tools_impl = VoiceAgentTools(
             coordinator,
             backend,
             call_id,
-            schema=config.get("extraction_schema") or {},
+            schema=schema,
         )
 
         session = AgentSession(
             stt=bundle.stt,
             llm=bundle.llm,
@@ -681,16 +719,17 @@ async def run_session(ctx: JobContext, settings: Settings) -> None:
             # 401 retries stalled every session start by ~4s.
             turn_detection="vad",
             # Snappier endpointing than defaults (NFR-1: median <=900ms).
             min_endpointing_delay=0.35,
             max_endpointing_delay=1.5,
-            # False-interruption hardening (owner report: background speech
-            # was cutting the agent off mid-sentence).
-            min_interruption_duration=0.35,
+            # Echo hardening: the agent's own TTS can loop back into its STT.
+            # These knobs prevent a false interruption from replaying the whole
+            # reply and stop hair-trigger retriggering on looped-back audio.
+            min_interruption_duration=0.5,
             false_interruption_timeout=2.0,
-            resume_false_interruption=True,
-            discard_audio_if_uninterruptible=False,
+            resume_false_interruption=False,
+            discard_audio_if_uninterruptible=True,
         )
         telemetry = TurnTelemetry(
             session=session,
             backend=backend,
             call_id=call_id,
@@ -702,10 +741,18 @@ async def run_session(ctx: JobContext, settings: Settings) -> None:
         if not await _is_connected(ctx):
             await ctx.connect()
 
         agent = DomainCallAgent(instructions=instructions, tools_impl=tools_impl)
         await session.start(room=ctx.room, agent=agent)
+        # Agent speaks first: the composed opening cannot be barged by
+        # background noise, and names are real (token-substituted).
+        await _speak_opening(
+            session,
+            config,
+            build_token_map(contact=parsed.contact, context=call_context),
+            parsed.contact,
+        )
     except Exception:
         logger.exception("Unhandled error in voice session (room=%s)", room_name)
         try:
             await _degrade(
                 ctx, backend, call_id, settings, "unexpected voice-agent error"
diff --git a/voice-agent/app/prompting.py b/voice-agent/app/prompting.py
index 444d24d..a5459d9 100644
--- a/voice-agent/app/prompting.py
+++ b/voice-agent/app/prompting.py
@@ -13,12 +13,16 @@ unit tested offline. The rendered prompt is structured, in order:
 """
 
 from __future__ import annotations
 
 import json
+import logging
+import re
 from typing import Any, Mapping, Optional
 
+logger = logging.getLogger("voice_agent.prompting")
+
 LOW_CONFIDENCE_THRESHOLD: float = 0.6
 MAX_ASKS_PER_FIELD: int = 3
 
 DISCLOSURE_HEADER = (
     "MANDATORY DISCLOSURE - your VERY FIRST utterance, spoken word-for-word:"
@@ -34,10 +38,167 @@ QUESTIONS_HEADER = "YOUR GOALS - information to collect during the call:"
 EXTRACTION_HEADER = "RECORDING ANSWERS - extraction discipline:"
 ESCALATION_HEADER = "WHEN TO WRAP UP:"
 
 LANGUAGE_NAMES = {"en": "English", "te": "Telugu", "hi": "Hindi"}
 
+#: Bracket placeholder tokens that may appear verbatim in config strings and
+#: must never be spoken/shipped. Mapped to real values; empty values are removed.
+KNOWN_TOKENS: tuple[str, ...] = (
+    "[Institution Name]",
+    "[Company Name]",
+    "[Student Name]",
+    "[Lead Name]",
+    "[Parent/Guardian Name]",
+    "[Agent Name]",
+    "[Expected Return Date]",
+)
+
+_BRACKET_ARTIFACT_RE = re.compile(r"\[[^\]]*\]")
+_DOUBLE_SPACE_RE = re.compile(r"\s{2,}")
+
+_TOOL_BLOCK_RE = re.compile(
+    r"<tool_call>.*?</tool_call>|<function=[^>]*>|<parameter=[^>]*>",
+    re.DOTALL | re.IGNORECASE,
+)
+_TOOL_CALLS_JSON_RE = re.compile(r'"[^"]*tool_calls[^"]*"\s*:\s*\[.*?\]', re.DOTALL)
+
+
+def scrub_speech_text(text: str) -> str:
+    """Remove LLM tool-call markup from text that will be spoken/saved.
+
+    Handles LiveKit-style inline markup (``<tool_call>...``, ``<function=...>``,
+    ``<parameter=...>``) and OpenAI-style ``\"tool_calls\": [...]`` JSON that a
+    model may emit as inline assistant text. Returns cleaned, stripped text.
+    """
+    original = str(text or "")
+    out = _TOOL_BLOCK_RE.sub(" ", original)
+    out = _TOOL_CALLS_JSON_RE.sub(" ", out)
+    out = _DOUBLE_SPACE_RE.sub(" ", out).strip()
+    if out != original.strip():
+        logger.debug("Scrubbed tool-call markup from agent text")
+    return out
+
+
+def apply_token_substitution(
+    text: str, tokens: Optional[Mapping[str, str]] = None
+) -> str:
+    """Replace known bracket tokens with real values; empty -> removed.
+
+    After substitution, any remaining ``[...]`` placeholder is stripped so a
+    bare bracket never ships. Returns cleaned text.
+    """
+    if not text:
+        return text
+    out = str(text)
+    for token, value in (tokens or {}).items():
+        out = out.replace(str(token), str(value) if value is not None else "")
+    # Safety net: strip any remaining placeholder tokens.
+    out = _BRACKET_ARTIFACT_RE.sub("", out)
+    return _DOUBLE_SPACE_RE.sub(" ", out).strip()
+
+
+def _first_name(*candidates: Optional[Mapping[str, Any]]) -> str:
+    """First known name found across contact cards (student/name/contact_name...)."""
+    for card in candidates:
+        if not isinstance(card, Mapping):
+            continue
+        for key in ("student_name", "name", "contact_name", "full_name", "lead_name"):
+            value = str(card.get(key) or "").strip()
+            if value:
+                return value
+    return ""
+
+
+def build_token_map(
+    contact: Optional[Mapping[str, Any]] = None,
+    context: Optional[Mapping[str, Any]] = None,
+    agent_name: str = "",
+) -> dict[str, str]:
+    """Resolve known placeholder tokens to real values for this call.
+
+    ``contact`` is the contact card packed in room/token metadata; ``context``
+    is the backend's call-context JSON (institution_name + optional contact).
+    ``[Expected Return Date]`` has no data source, so it maps to "" (dropped).
+
+    ``agent_name`` fills ``[Agent Name]``; empty falls back to
+    "an AI assistant" so disclosures never dangle.
+    """
+    ctx = context if isinstance(context, Mapping) else {}
+    ctx_contact = ctx.get("contact") if isinstance(ctx.get("contact"), Mapping) else {}
+    institution = str(ctx.get("institution_name") or "").strip()
+    name = _first_name(contact, ctx_contact)
+    who = str(agent_name or "").strip() or "an AI assistant"
+    return {
+        "[Institution Name]": institution,
+        "[Company Name]": institution,
+        "[Student Name]": name,
+        "[Lead Name]": name,
+        "[Parent/Guardian Name]": name,
+        "[Agent Name]": who,
+        "[Expected Return Date]": "",
+    }
+
+
+_CARD_PARENT_KEYS = ("parent_name", "parent", "guardian", "contact_person")
+_CARD_SUBJECT_KEYS = ("student_name", "full_name", "contact_name", "lead_name", "candidate_name", "name")
+
+
+def _card_value(card: Mapping[str, Any], keys: tuple[str, ...]) -> str:
+    for key in keys:
+        value = str(card.get(key) or "").strip()
+        if value:
+            return value
+    return ""
+
+
+def build_opening_line(
+    config: Mapping[str, Any],
+    tokens: Optional[Mapping[str, str]] = None,
+    contact: Optional[Mapping[str, Any]] = None,
+) -> str:
+    """Deterministic opening: disclosure + greeting + first question.
+
+    Everything is token-substituted, so no ``[...]`` placeholder can ship.
+    Returns "" when there is no disclosure script GÇö the caller then falls
+    back to the prompt-driven auto-turn.
+    """
+    tok = dict(tokens or {})
+    disclosure = apply_token_substitution(_disclosure_text(config), tok)
+    if not disclosure:
+        return ""
+    card = contact if isinstance(contact, Mapping) else {}
+    parent = _card_value(card, _CARD_PARENT_KEYS)
+    subject = _card_value(card, _CARD_SUBJECT_KEYS)
+    institution = tok.get("[Institution Name]", "") or tok.get("[Company Name]", "")
+    who = tok.get("[Agent Name]", "") or "an AI assistant"
+    if parent and subject and parent != subject:
+        if institution:
+            greet = f"Hello {parent}, this is {who} calling from {institution} about {subject}."
+        else:
+            greet = f"Hello {parent}, this is {who} calling about {subject}."
+    elif subject:
+        if institution:
+            greet = f"Hello {subject}, this is {who} calling from {institution}."
+        else:
+            greet = f"Hello {subject}, this is {who} calling."
+    elif institution:
+        greet = f"Hello, this is {who} calling from {institution}."
+    else:
+        greet = "Hello."
+    first_question = ""
+    flow = config.get("question_flow") if isinstance(config, Mapping) else []
+    if isinstance(flow, list):
+        for item in flow:
+            text_value = apply_token_substitution(_question_text(item), tok)
+            if text_value:
+                first_question = text_value
+                break
+    opening = f"{disclosure} {greet}"
+    if first_question:
+        opening += f" {first_question}"
+    return scrub_speech_text(opening)
+
 
 def _disclosure_text(config: Mapping[str, Any]) -> str:
     """Disclosure script, accepting both the platform key and the legacy one."""
     raw = config.get("disclosure_script")
     if not raw:
@@ -190,27 +351,36 @@ def render_caller_context(contact: Mapping[str, Any]) -> str:
     )
     return "\n".join(lines)
 
 
 def render_system_prompt(
-    config: Mapping[str, Any], contact: Optional[Mapping[str, Any]] = None
+    config: Mapping[str, Any],
+    contact: Optional[Mapping[str, Any]] = None,
+    tokens: Optional[Mapping[str, str]] = None,
 ) -> str:
     """Render the full agent instructions from an agent-version config.
 
     ``contact`` (optional, P0-2) is the flat custom-field card packed into the
     room/token metadata; when present a CALLER CONTEXT section personalizes
     the prompt and adds the parent-verification rule.
+
+    ``tokens`` (optional, C) is a resolved token map (``[Institution Name]`` ->
+    value) applied to the disclosure, system_prompt, and question_flow text so
+    literal ``[Institution Name]`` placeholders never ship. Empty values are
+    removed.
     """
     sections: list[str] = []
 
     # 1. Disclosure FIRST and verbatim.
-    disclosure = _disclosure_text(config)
+    disclosure = apply_token_substitution(_disclosure_text(config), tokens)
     if disclosure:
         sections.append(f"{DISCLOSURE_HEADER}\n{disclosure}")
 
     # 2. Role & mission GÇö platform baseline, then the creator's definition.
-    system_prompt = str(config.get("system_prompt") or "").strip()
+    system_prompt = apply_token_substitution(
+        str(config.get("system_prompt") or "").strip(), tokens
+    )
     role_lines: list[str] = [
         "You are a human-sounding phone agent making a single outbound call.",
         "This is a real-time SPOKEN conversation: the caller hears your words read aloud by a voice engine.",
         "Your job is to have a natural short conversation, understand the caller, and complete the goals below.",
     ]
@@ -302,11 +472,11 @@ def render_system_prompt(
     # 5. Goals (question flow) as a checklist, woven naturally.
     question_flow = config.get("question_flow") or []
     goal_items: list[str] = []
     number = 0
     for item in question_flow:
-        text = _question_text(item)
+        text = apply_token_substitution(_question_text(item), tokens)
         if not text:
             continue
         number += 1
         goal_items.append(f"{number}. {text}")
     if goal_items:
@@ -329,10 +499,14 @@ def render_system_prompt(
         EXTRACTION_HEADER,
         "- The moment the caller states something that answers any goal above, IMMEDIATELY "
         "call `record_extracted_field(field_name, value, confidence)` in that same turn. "
         "Do not wait until the end of the call.",
         "- Use the EXACT field names listed below. Value must be quoted as the caller said it.",
+        "- Invoke `record_extracted_field` through your real FUNCTION-CALLING mechanism. "
+        "NEVER write tool-call markup into your spoken text - never output `<tool_call>`, "
+        "`<function=...>`, `<parameter=...>`, or `tool_calls` JSON. If you don't yet have a "
+        "real value, keep asking a short clarifying question - do not invent one or fake a call.",
         "- Give an honest confidence between 0.0 and 1.0. If you clearly heard it, say 0.9. "
         "If you are guessing, do NOT record - ask a short clarifying question instead.",
         "- NEVER fabricate or guess a value. Uncertain means ask again, differently.",
         (
             f"- If your confidence for a value stays below {LOW_CONFIDENCE_THRESHOLD}, treat that field as NOT captured: "
diff --git a/voice-agent/tests/test_opening_line.py b/voice-agent/tests/test_opening_line.py
new file mode 100644
index 0000000..fbf0e73
--- /dev/null
+++ b/voice-agent/tests/test_opening_line.py
@@ -0,0 +1,70 @@
+"""Deterministic protected opening line: disclosure + greeting + first question."""
+import asyncio
+
+from app import pipeline as pipeline_module
+from app.prompting import build_opening_line, build_token_map
+
+CONFIG = {
+    "disclosure_script": "Hi, this is [Agent Name] calling from [Company Name].",
+    "question_flow": [{"question": "Why was [Student Name] absent?"}],
+}
+
+
+def _tokens(contact, institution="Demo School"):
+    return build_token_map(contact=contact, context={"institution_name": institution})
+
+
+def test_opening_line_school_card() -> None:
+    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
+    out = build_opening_line(CONFIG, _tokens(contact), contact)
+    assert out.startswith("Hi, this is an AI assistant calling from Demo School.")
+    assert "Suresh Kumar" in out
+    assert "Aarav Kumar" in out
+    assert "Why was Aarav Kumar absent?" in out
+    assert "[" not in out and "]" not in out
+
+
+def test_opening_line_lead_card() -> None:
+    contact = {"lead_name": "Riya"}
+    out = build_opening_line(CONFIG, _tokens(contact, "Acme Realty"), contact)
+    assert "Riya" in out and "Acme Realty" in out
+    assert "[" not in out and "]" not in out
+
+
+def test_opening_line_no_names_no_invention() -> None:
+    out = build_opening_line(CONFIG, _tokens({}), {})
+    assert "Hello" in out
+    assert "[" not in out and "]" not in out
+
+
+def test_opening_line_empty_without_disclosure() -> None:
+    assert build_opening_line({"question_flow": []}, {}, {}) == ""
+
+
+class _FakeSession:
+    def __init__(self) -> None:
+        self.said: list[tuple[str, bool]] = []
+
+    async def say(self, text: str, allow_interruptions: bool = True) -> None:
+        self.said.append((text, allow_interruptions))
+
+
+def test_speak_opening_protected_and_first() -> None:
+    session = _FakeSession()
+    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
+    tokens = build_token_map(contact=contact, context={"institution_name": "Demo School"})
+    spoken = asyncio.run(pipeline_module._speak_opening(session, CONFIG, tokens, contact))
+    assert spoken is True
+    assert len(session.said) == 1
+    text, allow_interruptions = session.said[0]
+    assert allow_interruptions is False
+    assert text.startswith("Hi, this is an AI assistant calling from Demo School.")
+    assert "Suresh Kumar" in text and "Aarav Kumar" in text
+    assert "[" not in text and "]" not in text
+
+
+def test_speak_opening_skips_without_disclosure() -> None:
+    session = _FakeSession()
+    spoken = asyncio.run(pipeline_module._speak_opening(session, {"question_flow": []}, {}, {}))
+    assert spoken is False
+    assert session.said == []
diff --git a/voice-agent/tests/test_token_substitution.py b/voice-agent/tests/test_token_substitution.py
new file mode 100644
index 0000000..1d31721
--- /dev/null
+++ b/voice-agent/tests/test_token_substitution.py
@@ -0,0 +1,91 @@
+"""Placeholder substitution (C): [Institution Name] / [Student Name] etc.
+
+Rendered prompt text (disclosure, system_prompt, question_flow) carried
+literal bracket tokens like [Institution Name] verbatim and the agent literally
+said them. We substitute known tokens with real values; empty values are
+removed so a bare bracket never ships.
+"""
+from __future__ import annotations
+
+from typing import Any, Dict
+
+from app.prompting import apply_token_substitution, build_token_map, render_system_prompt
+
+BASE: Dict[str, Any] = {
+    "disclosure_script": "Calling from [Institution Name] about [Student Name].",
+    "system_prompt": "You represent [Institution Name].",
+    "question_flow": [
+        {"question": "Is [Student Name] returning by [Expected Return Date]?"},
+    ],
+}
+
+
+def test_known_tokens_replaced() -> None:
+    tokens = {
+        "[Institution Name]": "Demo University",
+        "[Student Name]": "Alex Johnson",
+        "[Expected Return Date]": "",
+    }
+    rendered = render_system_prompt(BASE, tokens=tokens)
+
+    assert "Demo University" in rendered
+    assert "Alex Johnson" in rendered
+    assert "[Institution Name]" not in rendered
+    assert "[Student Name]" not in rendered
+    assert "[Expected Return Date]" not in rendered
+    assert "[" not in rendered, "no bare bracket may survive"
+
+
+def test_empty_value_removes_token() -> None:
+    rendered = render_system_prompt(BASE, tokens={"[Institution Name]": ""})
+    assert "[Institution Name]" not in rendered
+    assert "[" not in rendered
+
+
+def test_apply_token_substitution_pure() -> None:
+    out = apply_token_substitution(
+        "from [Institution Name] re [Student Name]",
+        {"[Institution Name]": "Demo University", "[Student Name]": ""},
+    )
+    assert "Demo University" in out
+    assert "[Student Name]" not in out
+    assert "[" not in out
+
+
+def test_build_token_map_resolves_names() -> None:
+    context = {"institution_name": "Demo University", "contact": {"name": "Alex Johnson"}}
+    contact = {"student_name": "Alex Johnson"}
+    m = build_token_map(contact=contact, context=context)
+    assert m["[Institution Name]"] == "Demo University"
+    assert m["[Student Name]"] == "Alex Johnson"
+    assert m["[Parent/Guardian Name]"] == "Alex Johnson"
+    assert m["[Expected Return Date]"] == ""
+
+
+def test_build_token_map_empty_institution() -> None:
+    m = build_token_map(contact={"name": "Alex Johnson"}, context={})
+    assert m["[Institution Name]"] == ""
+    assert m["[Student Name]"] == "Alex Johnson"
+    assert m["[Parent/Guardian Name]"] == "Alex Johnson"
+
+
+def test_build_token_map_falls_back_to_parsed_contact() -> None:
+    context = {"institution_name": "HS", "contact": {}}
+    m = build_token_map(contact={"name": "Priya"}, context=context)
+    assert m["[Student Name]"] == "Priya"
+
+
+def test_build_token_map_lead_gen_aliases() -> None:
+    m = build_token_map(
+        contact={"lead_name": "Riya"},
+        context={"institution_name": "Acme Realty"},
+        agent_name="Priya",
+    )
+    assert m["[Lead Name]"] == "Riya"
+    assert m["[Company Name]"] == "Acme Realty"
+    assert m["[Agent Name]"] == "Priya"
+    assert m["[Student Name]"] == "Riya"
+
+
+def test_build_token_map_agent_name_defaults_to_assistant() -> None:
+    assert build_token_map()["[Agent Name]"] == "an AI assistant"
