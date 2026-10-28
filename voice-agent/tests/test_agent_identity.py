"""The agent's human name and role travel from the platform to the caller.

Regression: every agent introduced itself as "an AI assistant", because the
worker fetched the agent name but never threaded it into the token map, the
system prompt or the generated opening.
"""
from __future__ import annotations

from app.prompting import (
    AI_ASSISTANT_FALLBACK,
    build_opening_line,
    build_token_map,
    render_system_prompt,
)


def _config(**overrides):
    config = {
        "agent_name": "Ananya",
        "agent_description": "School attendance follow-up",
        "disclosure_script": (
            "Hello, this is [Agent Name], an AI assistant from [Institution Name]. "
            "This call is recorded."
        ),
        "question_flow": [{"question": "Could you share the reason for the absence?"}],
        "system_prompt": "You call guardians of absent students.",
        "company_context": {"institution": "Acme School"},
    }
    config.update(overrides)
    return config


def test_token_map_fills_agent_name_and_falls_back():
    tokens = build_token_map(contact={}, agent_name="Ananya")
    assert tokens["[Agent Name]"] == "Ananya"
    assert build_token_map(contact={})["[Agent Name]"] == AI_ASSISTANT_FALLBACK


def test_system_prompt_states_the_name_and_role():
    prompt = render_system_prompt(_config())
    assert "Your name is Ananya, School attendance follow-up." in prompt
    assert "[Agent Name]" not in prompt


def test_opening_names_the_agent_once():
    config = _config()
    tokens = build_token_map(
        contact={},
        context={"institution_name": "Acme School"},
        agent_name="Ananya",
        company_context=config["company_context"],
    )
    opening = build_opening_line(config, tokens, {})
    assert "this is Ananya" in opening
    assert opening.count("Ananya") == 1, opening
    assert "[Agent Name]" not in opening


def test_bare_disclosure_still_introduces_the_agent_by_name():
    """An authored script that says nothing about identity must not leave the
    caller without a name — the generated intro carries it."""
    config = _config(
        disclosure_script="This call is recorded.",
        question_flow=[{"question": "May I speak with the guardian?"}],
    )
    tokens = build_token_map(
        contact={},
        context={"institution_name": "Acme School"},
        agent_name="Ananya",
        company_context=config["company_context"],
    )
    opening = build_opening_line(config, tokens, {})
    assert "This is Ananya calling from Acme School." in opening


def test_disclosure_without_the_name_adds_it_as_a_short_sentence():
    config = _config(
        disclosure_script=(
            "Hello, this is an AI assistant calling from [Institution Name]. "
            "This call is recorded."
        ),
    )
    tokens = build_token_map(
        contact={},
        context={"institution_name": "Acme School"},
        agent_name="Ananya",
        company_context=config["company_context"],
    )
    opening = build_opening_line(config, tokens, {})
    assert "I'm Ananya." in opening
    assert opening.count("Ananya") == 1
