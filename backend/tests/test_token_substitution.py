"""Bracket-token substitution ported from voice-agent/app/prompting.py."""
from __future__ import annotations

from app.services.token_substitution import (
    KNOWN_TOKENS,
    apply_token_substitution,
    build_token_map,
    declares_own_enterprise,
    resolve_org_name,
    resolve_spoken_name,
    unfilled_enterprise_keys,
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


def test_build_token_map_unfilled_clinic_name_never_borrows_institution() -> None:
    """A clinic agent belongs to its own practice; the tenant's name is not it."""
    tokens = build_token_map(
        {}, institution="CMR College of Engineering & Technology",
        company_context={"clinic_name": "[Clinic Name]"},
    )
    assert tokens["[Company Name]"] == "our company"
    assert tokens["[Clinic Name]"] == "our clinic"


def test_resolve_org_name_skips_unfilled_placeholders() -> None:
    assert resolve_org_name({"company_name": "[Company Name]"}, "Acme Realty") == "Acme Realty"
    assert resolve_org_name({"clinic_name": "Sunrise Dental"}, "Acme Realty") == "Sunrise Dental"
    assert resolve_org_name(None, "Acme Realty") == "Acme Realty"


def test_resolve_spoken_name_keeps_tenant_name_for_absence_agents() -> None:
    """The absence agent represents the tenant's college, so CMR is correct."""
    assert resolve_spoken_name(
        {"institution_name": "[Institution Name]"},
        "CMR College of Engineering & Technology",
    ) == "CMR College of Engineering & Technology"
    assert resolve_spoken_name({}, "CMR College of Engineering & Technology") == (
        "CMR College of Engineering & Technology"
    )


def test_resolve_spoken_name_never_borrows_tenant_for_own_enterprise() -> None:
    """Kavya's service-feedback agent is a different enterprise from the college."""
    assert resolve_spoken_name(
        {"company_name": "[Company Name]"}, "CMR College of Engineering & Technology"
    ) == ""
    assert resolve_spoken_name(
        {"clinic_name": "[Clinic Name]"}, "CMR College of Engineering & Technology"
    ) == ""
    assert resolve_spoken_name(
        {"company_name": "Skyline Estates"}, "CMR College of Engineering & Technology"
    ) == "Skyline Estates"


def test_declares_own_enterprise_counts_unfilled_keys() -> None:
    assert declares_own_enterprise({"company_name": "[Company Name]"}) is True
    assert declares_own_enterprise({"institution_name": "[Institution Name]"}) is False
    assert declares_own_enterprise({}) is False


def test_unfilled_enterprise_keys_flags_placeholders_only() -> None:
    assert unfilled_enterprise_keys({"company_name": "[Company Name]"}) == ["company_name"]
    assert unfilled_enterprise_keys({"company_name": "Skyline Estates"}) == []
    assert unfilled_enterprise_keys({"institution_name": "[Institution Name]"}) == []


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
