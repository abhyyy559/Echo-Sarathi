"""Placeholder substitution (C): [Institution Name] / [Student Name] etc.

Rendered prompt text (disclosure, system_prompt, question_flow) carried
literal bracket tokens like [Institution Name] verbatim and the agent literally
said them. We substitute known tokens with real values; empty values are
removed so a bare bracket never ships.
"""
from __future__ import annotations

from typing import Any, Dict

from app.prompting import apply_token_substitution, build_token_map, render_system_prompt

BASE: Dict[str, Any] = {
    "disclosure_script": "Calling from [Institution Name] about [Student Name].",
    "system_prompt": "You represent [Institution Name].",
    "question_flow": [
        {"question": "Is [Student Name] returning by [Expected Return Date]?"},
    ],
}


def test_known_tokens_replaced() -> None:
    tokens = {
        "[Institution Name]": "Demo University",
        "[Student Name]": "Alex Johnson",
        "[Expected Return Date]": "",
    }
    rendered = render_system_prompt(BASE, tokens=tokens)

    assert "Demo University" in rendered
    assert "Alex Johnson" in rendered
    assert "[Institution Name]" not in rendered
    assert "[Student Name]" not in rendered
    assert "[Expected Return Date]" not in rendered
    assert "[" not in rendered, "no bare bracket may survive"


def test_empty_value_removes_token() -> None:
    rendered = render_system_prompt(BASE, tokens={"[Institution Name]": ""})
    assert "[Institution Name]" not in rendered
    assert "[" not in rendered


def test_apply_token_substitution_pure() -> None:
    out = apply_token_substitution(
        "from [Institution Name] re [Student Name]",
        {"[Institution Name]": "Demo University", "[Student Name]": ""},
    )
    assert "Demo University" in out
    assert "[Student Name]" not in out
    assert "[" not in out


def test_build_token_map_resolves_names() -> None:
    context = {"institution_name": "Demo University", "contact": {"name": "Alex Johnson"}}
    contact = {"student_name": "Alex Johnson"}
    m = build_token_map(contact=contact, context=context)
    assert m["[Institution Name]"] == "Demo University"
    assert m["[Student Name]"] == "Alex Johnson"
    assert m["[Parent/Guardian Name]"] == ""
    assert m["[Expected Return Date]"] == ""


def test_build_token_map_empty_institution() -> None:
    m = build_token_map(contact={"name": "Alex Johnson"}, context={})
    assert m["[Institution Name]"] == ""
    assert m["[Student Name]"] == "Alex Johnson"
    assert m["[Parent/Guardian Name]"] == ""


def test_build_token_map_resolves_parent_token_without_student_fallback() -> None:
    m = build_token_map(
        contact={"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"},
        context={"institution_name": "Demo School"},
    )
    assert m["[Student Name]"] == "Aarav Kumar"
    assert m["[Parent/Guardian Name]"] == "Suresh Kumar"


def test_build_token_map_resolves_parent_aliases() -> None:
    for key in ("parent", "guardian", "contact_person"):
        m = build_token_map(contact={"student_name": "Aarav", key: "Guardian Name"})
        assert m["[Parent/Guardian Name]"] == "Guardian Name"


def test_build_token_map_falls_back_to_parsed_contact() -> None:
    context = {"institution_name": "HS", "contact": {}}
    m = build_token_map(contact={"name": "Priya"}, context=context)
    assert m["[Student Name]"] == "Priya"


def test_build_token_map_lead_gen_aliases() -> None:
    m = build_token_map(
        contact={"lead_name": "Riya"},
        context={"institution_name": "Acme Realty"},
        agent_name="Priya",
    )
    assert m["[Lead Name]"] == "Riya"
    assert m["[Company Name]"] == "Acme Realty"
    assert m["[Agent Name]"] == "Priya"
    assert m["[Student Name]"] == "Riya"


def test_build_token_map_agent_name_defaults_to_assistant() -> None:
    assert build_token_map()["[Agent Name]"] == "an AI assistant"
