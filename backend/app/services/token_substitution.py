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
    "[Patient Name]",
    "[Parent/Guardian Name]",
    "[Agent Name]",
    "[Doctor Name]",
    "[Appointment Date]",
    "[Appointment Time]",
    "[Source]",
    "[Expected Return Date]",
)

_BRACKET_ARTIFACT_RE = re.compile(r"\[[^\]]*\]")
_DOUBLE_SPACE_RE = re.compile(r"\s{2,}")

_NAME_KEYS = (
    "student_name",
    "patient_name",
    "customer_name",
    "name",
    "contact_name",
    "full_name",
    "lead_name",
)
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

# Keys that say "this agent belongs to its OWN company/clinic/brand", as
# opposed to an absence agent, which represents the tenant's school. The
# tenant's name may stand in for an unfilled institution; it must never stand
# in here, or a college's service-feedback agent answers as the college.
_OWN_ENTERPRISE_KEYS: tuple[str, ...] = (
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


def filled_context(company_context: Any) -> dict[str, Any]:
    """Company facts with unfilled preset tokens removed.

    ``"[Service Date]"`` is not a fact; leaving it in the prompt's context
    block invites the model to read the bracket out loud.
    """
    if not isinstance(company_context, Mapping):
        return {}
    return {
        str(key): value
        for key, value in company_context.items()
        if not is_bracket_placeholder(value)
    }


def resolve_org_name(company_context: Any, fallback: str = "") -> str:
    """Name this tenant wants spoken, from its vertical's company_context."""
    return _context_value(company_context, *_ORG_NAME_KEYS) or str(fallback or "").strip()


def declares_own_enterprise(company_context: Any) -> bool:
    """True when the version says it belongs to its own company/clinic/brand.

    The key counts even while its value is still the preset's ``[Company
    Name]``: the agent was authored for a different enterprise, and the
    tenant's name (a college, say) is not that enterprise.
    """
    if not isinstance(company_context, Mapping):
        return False
    return any(
        str(company_context.get(key) or "").strip() for key in _OWN_ENTERPRISE_KEYS
    )


def unfilled_enterprise_keys(company_context: Any) -> list[str]:
    """Own-enterprise keys still holding an unfilled preset token.

    ``institution`` is deliberately excluded: an absence agent is allowed to
    inherit the tenant's name, so its placeholder is not an authoring error.
    """
    if not isinstance(company_context, Mapping):
        return []
    return [
        key
        for key in _OWN_ENTERPRISE_KEYS
        if is_bracket_placeholder(company_context.get(key))
    ]


def resolve_spoken_name(company_context: Any, tenant_name: str = "") -> str:
    """Enterprise name this call may speak.

    ``tenant_name`` is the account's own organization. It is the right
    fallback for an absence agent (the tenant IS the college) or a version
    with no vertical identity at all — but not for an agent authored as
    another enterprise. Returning "" there lets the caller-facing templates
    use their neutral fallback instead of introducing the agent with the
    tenant's name.
    """
    name = resolve_org_name(company_context)
    if name or declares_own_enterprise(company_context):
        return name
    return str(tenant_name or "").strip()


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
    # An agent authored for its own enterprise never borrows the tenant's
    # name; an unfilled name speaks neutrally ("our company") until filled.
    own = declares_own_enterprise(company_context)
    own_name = _context_value(company_context, *_OWN_ENTERPRISE_KEYS)
    company_name = own_name or ("our company" if own else org)
    clinic_name = own_name or ("our clinic" if own else org)
    return {
        "[Institution Name]": org,
        "[Company Name]": company_name,
        "[Clinic Name]": clinic_name,
        # Per-call card data wins over the version's generic context: the
        # lead knows which property/locality this call is about, and a
        # company-context default would make every call speak the same one.
        "[Property Name]": _first(card, ("property_name",))
        or _context_value(company_context, "property_name"),
        "[Locality]": _first(card, ("locality", "area"))
        or _context_value(company_context, "locality"),
        "[Service Type]": _first(card, ("service_type",))
        or _context_value(company_context, "service_type"),
        "[Service Date]": _first(card, ("service_date",))
        or _context_value(company_context, "service_date"),
        "[Student Name]": name,
        "[Lead Name]": name,
        "[Contact Name]": name,
        "[Customer Name]": name,
        "[Patient Name]": name,
        "[Parent/Guardian Name]": parent,
        "[Agent Name]": who,
        # Clinic presets put the slot in company_context; a contact card may
        # also carry it per call, so the contact wins when both are present.
        "[Doctor Name]": _context_value(company_context, "doctor_name")
        or _first(card, ("doctor_name", "doctor")),
        "[Appointment Date]": _first(card, ("appointment_date", "date"))
        or _context_value(company_context, "appointment_date"),
        "[Appointment Time]": _first(card, ("appointment_time", "time"))
        or _context_value(company_context, "appointment_time"),
        "[Source]": _first(card, ("source", "lead_source"))
        or _context_value(company_context, "source", "lead_source"),
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
