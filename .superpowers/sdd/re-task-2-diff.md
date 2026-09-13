# Commits

840b6af feat: RE sample leads and automated dry-run gate

# Stat

 backend/tests/test_real_estate_dry_run.py | 143 ++++++++++++++++++++++++++++++
 sample_real_estate_contacts.csv           |   5 ++
 2 files changed, 148 insertions(+)

# Full diff

diff --git a/backend/tests/test_real_estate_dry_run.py b/backend/tests/test_real_estate_dry_run.py
new file mode 100644
index 0000000..dab0b1f
--- /dev/null
+++ b/backend/tests/test_real_estate_dry_run.py
@@ -0,0 +1,143 @@
+"""Real-estate agent gate: preset tokens, prompt rendering, dry-run structure."""
+from __future__ import annotations
+
+import json
+import re
+from pathlib import Path
+from types import SimpleNamespace
+from typing import Any
+
+from conftest import auth_headers, register
+from test_playground_text import chat, groq_client, script, tool_call
+
+_PRESET = Path(__file__).resolve().parents[2] / "domain-configs" / "presets" / "real-estate-lead-qualification.json"
+
+# Tokens the maps resolve (backend build_token_map + voice map).
+_MAPPED_TOKENS = {
+    "[Institution Name]", "[Company Name]", "[Student Name]", "[Lead Name]",
+    "[Parent/Guardian Name]", "[Agent Name]", "[Expected Return Date]",
+}
+
+
+def _payload() -> dict[str, Any]:
+    return json.loads(_PRESET.read_text(encoding="utf-8"))["version_payload"]
+
+
+def test_preset_spoken_regions_use_only_mapped_tokens() -> None:
+    payload = _payload()
+    spoken = "\n".join(
+        [
+            payload["disclosure_script"],
+            payload["system_prompt"],
+            *[step["question"] for step in payload["question_flow"]],
+        ]
+    )
+    tokens = set(re.findall(r"\[[^\]]*\]", spoken))
+    assert tokens, "expected at least the Company/Lead/Agent tokens"
+    assert tokens <= _MAPPED_TOKENS, f"unmapped spoken tokens: {tokens - _MAPPED_TOKENS}"
+
+
+def test_preset_renders_with_real_names() -> None:
+    from app.routers.playground import _render_text_system_prompt
+
+    payload = _payload()
+    config = SimpleNamespace(
+        disclosure_script=payload["disclosure_script"],
+        system_prompt=payload["system_prompt"],
+        company_context={},
+        question_flow=payload["question_flow"],
+        extraction_schema=payload["extraction_schema"],
+    )
+    contact = {"lead_name": "Riya Sharma", "city": "Hyderabad", "budget_band": "80 lakhs"}
+    prompt = _render_text_system_prompt(config, contact=contact, institution="Acme Realty")
+    assert "Riya Sharma" in prompt
+    assert "Acme Realty" in prompt
+    assert "Hyderabad" in prompt
+    assert "[Lead Name]" not in prompt
+    assert "[Company Name]" not in prompt
+    leftovers = set(re.findall(r"\[[^\]]*\]", prompt))
+    # [REQUIRED] is a platform marker the renderer adds for required fields,
+    # not a placeholder leak GÇö it is the only bracket token permitted here.
+    assert leftovers <= {"[REQUIRED]"}, f"unsubstituted tokens in rendered prompt: {leftovers}"
+
+
+def test_real_estate_dry_run_structural_gate(groq_client, session_factory):
+    from sqlalchemy import select
+
+    from app.models import Call, Campaign, Contact
+
+    client = groq_client
+    token, user = register(client)
+    payload = _payload()
+    agent = client.post(
+        "/api/agents", json={"name": "RE Gate Agent", "description": ""},
+        headers=auth_headers(token),
+    )
+    assert agent.status_code == 201, agent.text
+    version = client.post(
+        f"/api/agents/{agent.json()['id']}/versions", json=payload,
+        headers=auth_headers(token),
+    )
+    assert version.status_code in (200, 201), version.text
+    version_id = version.json()["id"]
+
+    with session_factory() as db:
+        campaign = Campaign(
+            name="RE Gate", org_id=user["org_id"],
+            agent_version_id=version_id, status="draft",
+        )
+        db.add(campaign)
+        db.flush()
+        for name, phone, custom in [
+            ("L1", "+919812345611", {"lead_name": "Riya Sharma", "city": "Hyderabad"}),
+            ("L2", "+919812345612", {"lead_name": "Arjun Rao", "city": "Bengaluru"}),
+            ("L3", "+919812345613", {"lead_name": "Meera Iyer", "city": "Chennai"}),
+        ]:
+            db.add(Contact(
+                campaign_id=campaign.id, name=name, phone=phone,
+                status="pending_review", custom_fields=custom,
+            ))
+        db.commit()
+        campaign_id = campaign.id
+
+    # Personas answer positionally; the gate asserts STRUCTURE (persistence,
+    # markup absence, schema membership), not content. Script accounting: each
+    # contact consumes opening chat + record tool + follow-up chat + end_call
+    # tool + spare chat = 5 Groq calls (round-robin personas never end early).
+    script(
+        chat("Hello, disclosure line. Am I speaking with Riya?"),
+        tool_call("record_extracted_field", {"field_name": "budget_band", "value": "80 lakhs", "confidence": 0.9}),
+        chat("Thanks, noted."),
+        tool_call("end_call", {"summary": "done 1"}),
+        chat("Goodbye."),
+        chat("Hello, disclosure line. Am I speaking with Arjun?"),
+        tool_call("record_extracted_field", {"field_name": "locality_preference", "value": "Madhapur", "confidence": 0.85}),
+        chat("Thanks, noted."),
+        tool_call("end_call", {"summary": "done 2"}),
+        chat("Goodbye."),
+        chat("Hello, disclosure line. Am I speaking with Meera?"),
+        tool_call("record_extracted_field", {"field_name": "property_type", "value": "2BHK", "confidence": 0.8}),
+        chat("Thanks, noted."),
+        tool_call("end_call", {"summary": "done 3"}),
+        chat("Goodbye."),
+    )
+    resp = client.post(
+        f"/api/playground/campaigns/{campaign_id}/dry-run",
+        json={},
+        headers=auth_headers(token),
+    )
+    assert resp.status_code == 200, resp.text
+    report = resp.json()
+    assert report["contacts_run"] == 3
+    assert report["results"][0]["extracted_fields"][0]["field_name"] == "budget_band"
+    assert all(r["status"] == "completed" for r in report["results"])
+    schema_keys = set(payload["extraction_schema"])
+    with session_factory() as db:
+        for result in report["results"]:
+            for turn in result["transcript"]:
+                assert "[" not in turn["text"] and "]" not in turn["text"]
+                assert "<tool_call>" not in turn["text"]
+            for field in result["extracted_fields"]:
+                assert field["field_name"] in schema_keys
+        rows = db.scalars(select(Call).where(Call.campaign_id == campaign_id)).all()
+        assert len(rows) == 3 and all(c.kind == "dry-run" for c in rows)
diff --git a/sample_real_estate_contacts.csv b/sample_real_estate_contacts.csv
new file mode 100644
index 0000000..5758d00
--- /dev/null
+++ b/sample_real_estate_contacts.csv
@@ -0,0 +1,5 @@
+name,phone,lead_name,city,property_interest,budget_band
+Riya Sharma,+919812345611,Riya Sharma,Hyderabad,2BHK apartment,60-80 lakhs
+Arjun Rao,+919812345612,Arjun Rao,Bengaluru,3BHK apartment,1-1.3 crore
+Meera Iyer,+919812345613,Meera Iyer,Chennai,Residential plot,40-60 lakhs
+Karan Mehta,+919812345614,Karan Mehta,Pune,2BHK apartment,70-90 lakhs
