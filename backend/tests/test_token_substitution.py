"""Bracket-token substitution ported from voice-agent/app/prompting.py."""
from __future__ import annotations

from app.services.token_substitution import (
    KNOWN_TOKENS,
    apply_token_substitution,
    build_token_map,
    resolve_org_name,
)


def test_known_tokens_cover_lead_gen_aliases() -> None:
    assert set(KNOWN_TOKENS) >= {
        "[Institution Name]",
        "[Company Name]",
        "[Student Name]",
        "[Lead Name]",
        "[Parent/Guardian Name]",
        "[Agent Name]",
        "[Expected Return Date]",
    }


def test_build_token_map_resolves_names_and_institution() -> None:
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
    tokens = build_token_map(contact, institution="Demo School")
    assert tokens["[Student Name]"] == "Aarav Kumar"
    assert tokens["[Parent/Guardian Name]"] == "Suresh Kumar"
    assert tokens["[Institution Name]"] == "Demo School"
    assert tokens["[Company Name]"] == "Demo School"


def test_build_token_map_lead_style_contact() -> None:
    tokens = build_token_map({"lead_name": "Riya", "city": "Hyderabad"}, institution="Acme Realty")
    assert tokens["[Lead Name]"] == "Riya"
    assert tokens["[Student Name]"] == "Riya"


def test_build_token_map_agent_name_defaults_to_assistant() -> None:
    assert build_token_map({})["[Agent Name]"] == "an AI assistant"
    assert build_token_map({}, agent_name="Priya")["[Agent Name]"] == "Priya"


def test_apply_token_substitution_replaces_and_drops_empties() -> None:
    tokens = build_token_map({"student_name": "Aarav"}, institution="")
    out = apply_token_substitution(
        "Hello [Parent/Guardian Name], calling from [Institution Name] about [Student Name].",
        tokens,
    )
    assert "[Parent/Guardian Name]" not in out
    assert "[Institution Name]" not in out
    assert "Aarav" in out
    assert "  " not in out


def test_apply_token_substitution_strips_unknown_brackets() -> None:
    out = apply_token_substitution("See [Something Else] today.", {})
    assert "[" not in out and "]" not in out
    assert out == "See today."


def test_build_token_map_resolves_vertical_tokens_from_company_context() -> None:
    tokens = build_token_map(
        {"lead_name": "Riya"},
        institution="Acme Realty",
        company_context={
            "company_name": "Skyline Estates",
            "property_name": "Green Meadows",
            "locality": "Kondapur",
        },
    )
    assert tokens["[Company Name]"] == "Skyline Estates"
    assert tokens["[Institution Name]"] == "Acme Realty"
    assert tokens["[Property Name]"] == "Green Meadows"
    assert tokens["[Locality]"] == "Kondapur"


def test_build_token_map_clinic_name_falls_back_to_institution() -> None:
    tokens = build_token_map(
        {}, institution="Sunrise Dental", company_context={"clinic_name": "[Clinic Name]"}
    )
    assert tokens["[Clinic Name]"] == "Sunrise Dental"


def test_resolve_org_name_skips_unfilled_placeholders() -> None:
    assert resolve_org_name({"company_name": "[Company Name]"}, "Acme Realty") == "Acme Realty"
    assert resolve_org_name({"clinic_name": "Sunrise Dental"}, "Acme Realty") == "Sunrise Dental"
    assert resolve_org_name(None, "Acme Realty") == "Acme Realty"


def test_apply_token_substitution_leaves_no_holes_in_preset_opening() -> None:
    tokens = build_token_map(
        {},
        institution="Skyline Estates",
        company_context={
            "company_name": "Skyline Estates",
            "property_name": "Green Meadows",
            "locality": "Kondapur",
        },
    )
    out = apply_token_substitution(
        "Hello, this is Priya from [Company Name]. I am calling about your "
        "enquiry for [Property Name] in [Locality].",
        tokens,
    )
    assert out == (
        "Hello, this is Priya from Skyline Estates. I am calling about your "
        "enquiry for Green Meadows in Kondapur."
    )


def test_apply_token_substitution_falsy_passthrough() -> None:
    assert apply_token_substitution("", {}) == ""
