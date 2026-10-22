"""Which chain member answers first, per call language.

Call 21 proved the ordering matters more than the prompt: Groq's qwen wrote
grammatical-looking but meaningless Telugu at 160 ms, while the Indic-trained
member wrote correct code-mixed Telugu at ~300 ms.
"""

from types import SimpleNamespace

from app.pipeline import SPOKEN_INDIC_LLM_PROVIDER, FallbackLLM, _preferred_llm_provider


def _chain(*labels: str) -> FallbackLLM:
    members = [SimpleNamespace(model=f"{label}-model") for label in labels]
    return FallbackLLM(members, provider_names=list(labels))


def test_english_calls_keep_the_fastest_member_first():
    llm = _chain("groq", "groq", "sarvam")
    assert llm._member_order() == [0, 1, 2]
    assert llm._pick_member() == 0


def test_indic_calls_start_at_the_indic_member():
    llm = FallbackLLM(
        [SimpleNamespace(model=m) for m in ("a", "b", "c")],
        provider_names=["groq", "groq-secondary", SPOKEN_INDIC_LLM_PROVIDER],
        prefer_provider=SPOKEN_INDIC_LLM_PROVIDER,
    )
    assert llm._member_order() == [2, 0, 1]
    assert llm._pick_member() == 2


def test_a_cooled_indic_member_falls_back_without_skipping_the_tier():
    llm = FallbackLLM(
        [SimpleNamespace(model=m) for m in ("a", "b", "c")],
        provider_names=["groq", "groq", SPOKEN_INDIC_LLM_PROVIDER],
        prefer_provider=SPOKEN_INDIC_LLM_PROVIDER,
    )
    llm._mark_down(2)
    assert llm._pick_member() == 0
    assert llm._pick_member(exclude={0}) == 1


def test_preference_is_ignored_when_the_chain_has_no_such_member():
    assert _preferred_llm_provider("te", ["groq", "velona"], ["qwen", "deepseek"]) is None
    assert _preferred_llm_provider("en", ["groq", "sarvam"], ["qwen", "sarvam-m"]) is None
    assert _preferred_llm_provider("te", ["groq", "sarvam"], ["qwen", "x"]) == "sarvam"


def test_an_indic_model_is_matched_by_model_name_too():
    assert (
        _preferred_llm_provider("hi", ["groq", "overflow"], ["qwen", "sarvam-105b-conversations"])
        == "overflow"
    )
