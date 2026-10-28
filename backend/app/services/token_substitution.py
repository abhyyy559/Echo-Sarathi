"""Bracket-token substitution ported from voice-agent/app/prompting.py.

Keep the two in sync: KNOWN_TOKENS here must cover the same placeholder
names the voice worker understands, plus the lead-gen aliases presets use
([Lead Name], [Company Name], [Agent Name]).
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional

KNOWN_TOKENS: tuple[str, ...] = (
    "[Institution Name]",
    "[Company Name]",
    "[Clinic Name]",
    "[Property Name]",
    "[Locality]",
    "[Service Type]",
    "[Service Date]",
    "[Student Name]",
    "[Lead Name]",
    "[Contact Name]",
    "[Customer Name]",
    "[Parent/Guardian Name]",
    "[Agent Name]",
    "[Source]",
    "[Expected Return Date]",
)

_BRACKET_ARTIFACT_RE = re.compile(r"\[[^\]]*\]")
_DOUBLE_SPACE_RE = re.compile(r"\s{2,}")

_NAME_KEYS = ("student_name", "name", "contact_name", "full_name", "lead_name")
_PARENT_KEYS = ("parent_name", "parent", "guardian", "contact_person")


def is_bracket_placeholder(value: Any) -> bool:
    """True for an unfilled template token such as ``[Institution Name]``.

    Presets ship bracket tokens for a tenant to fill in. One stored verbatim in
    ``company_context`` is NOT a name: it used to win the institution lookup and
    reach the call, where the worker strips the brackets and the caller hears a
    hole ("I am from ." / "నేను నుండి AI అసిస్టెంట్").
    """
    text = str(value or "").strip()
    return text.startswith("[") and text.endswith("]") and len(text) > 2


def _first(contact: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(contact.get(key) or "").strip()
        if value:
            return value
    return ""


# Every vertical names the tenant differently in company_context. Presets ship
# these as unfilled bracket tokens, so a placeholder must lose to the real org
# name instead of reaching the caller as "I am calling from .".
_ORG_NAME_KEYS: tuple[str, ...] = (
    "institution",
    "institution_name",
    "company_name",
    "clinic_name",
    "business_name",
    "organization_name",
)


def _context_value(company_context: Any, *keys: str) -> str:
    if not isinstance(company_context, Mapping):
        return ""
    for key in keys:
        value = company_context.get(key)
        if isinstance(value, str) and value.strip() and not is_bracket_placeholder(value):
            return value.strip()
    return ""


def resolve_org_name(company_context: Any, fallback: str = "") -> str:
    """Name this tenant wants spoken, from its vertical's company_context."""
    return _context_value(company_context, *_ORG_NAME_KEYS) or str(fallback or "").strip()


def build_token_map(
    contact: Optional[Mapping[str, Any]] = None,
    institution: str = "",
    agent_name: str = "",
    company_context: Any = None,
) -> dict[str, str]:
    """Resolve known placeholder tokens to real values for this call."""
    card = contact if isinstance(contact, Mapping) else {}
    name = _first(card, _NAME_KEYS)
    parent = _first(card, _PARENT_KEYS)
    org = str(institution or "").strip()
    who = str(agent_name or "").strip() or "an AI assistant"
    return {
        "[Institution Name]": org,
        "[Company Name]": _context_value(company_context, "company_name") or org,
        "[Clinic Name]": _context_value(company_context, "clinic_name") or org,
        "[Property Name]": _context_value(company_context, "property_name"),
        "[Locality]": _context_value(company_context, "locality"),
        "[Service Type]": _context_value(company_context, "service_type"),
        "[Service Date]": _context_value(company_context, "service_date"),
        "[Student Name]": name,
        "[Lead Name]": name,
        "[Contact Name]": name,
        "[Customer Name]": name,
        "[Parent/Guardian Name]": parent,
        "[Agent Name]": who,
        "[Source]": _context_value(company_context, "source", "lead_source"),
        "[Expected Return Date]": "",
    }


def apply_token_substitution(
    text: str, tokens: Optional[Mapping[str, str]] = None
) -> str:
    """Replace known bracket tokens; empties removed, leftovers stripped."""
    if not text:
        return text
    out = str(text)
    for token, value in (tokens or {}).items():
        out = out.replace(str(token), str(value) if value is not None else "")
    out = _BRACKET_ARTIFACT_RE.sub("", out)
    return _DOUBLE_SPACE_RE.sub(" ", out).strip()
