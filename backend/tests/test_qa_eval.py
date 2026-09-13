"""Tests for the qa-eval harness (offline/simulated mode)."""
import pytest
from qa_eval.harness import EvalCase, ExpectedField, QAEvalHarness


@pytest.fixture()
def harness():
    return QAEvalHarness(backend_url="http://localhost:9999", api_token="test")


def _make_case(transcript, expected):
    return EvalCase(
        name="test-absent-student",
        agent_version_id=1,
        to_number="+917842594002",
        expected_fields=expected,
        simulated_transcript=transcript,
    )


AGENT_TRANSCRIPT = [
    {"speaker": "agent", "text": "Hello, I am an AI assistant calling from the university."},
    {"speaker": "user", "text": "Yes, this is Mrs. Sharma speaking."},
    {"speaker": "agent", "text": "Mrs. Sharma, I'm calling about your son Rahul's absence today. Could you share the reason?"},
    {"speaker": "user", "text": "Rahul has a fever since yesterday. He is sick."},
    {"speaker": "agent", "text": "Sorry to hear that. When do you expect Rahul to return?"},
    {"speaker": "user", "text": "He should be back by Friday, that is August 29th."},
    {"speaker": "agent", "text": "Thank you. I have noted that Rahul will return on August 29th. Is there anything else?"},
    {"speaker": "user", "text": "No, that is all."},
    {"speaker": "agent", "text": "Thank you for your time. Have a good day."},
]


def test_simulated_extraction_pass(harness):
    case = _make_case(
        AGENT_TRANSCRIPT,
        [
            ExpectedField("reason_for_absence", "fever"),
            ExpectedField("expected_return_date", "august 29"),
        ],
    )
    result = harness._run_simulated(case)
    assert result.status == "pass"
    assert result.extraction_accuracy == 1.0
    assert all(e.matched for e in result.extractions)


def test_simulated_extraction_fail(harness):
    case = _make_case(
        AGENT_TRANSCRIPT,
        [
            ExpectedField("reason_for_absence", "dengue"),  # not in transcript
        ],
    )
    result = harness._run_simulated(case)
    assert result.status == "fail"
    assert result.extraction_accuracy == 0.0


def test_simulated_empty_transcript(harness):
    case = _make_case([], [ExpectedField("reason_for_absence", "fever")])
    result = harness._run_simulated(case)
    assert result.status == "fail"
    assert len(result.extractions) == 1
    assert not result.extractions[0].matched


def test_eval_result_report(harness):
    case = _make_case(
        AGENT_TRANSCRIPT,
        [ExpectedField("reason_for_absence", "fever")],
    )
    result = harness._run_simulated(case)
    report = result.report()
    assert "test-absent-student" in report
    assert "PASS" in report or "extraction accuracy" in report
    assert isinstance(report, str)


def test_latency_percentiles():
    from qa_eval.harness import LatencyMetrics
    m = LatencyMetrics(
        stt_final_ms=[100, 200, 300],
        llm_first_token_ms=[500, 600, 700],
        tts_first_audio_ms=[200, 300, 400],
        e2e_ms=[800, 1100, 1400],
    )
    assert m.stt_p50 == 200
    assert m.llm_p50 == 600
    assert m.tts_p50 == 300
    assert m.e2e_p50 == 1100
    assert m.summary()["turns"] == 3


def test_latency_empty():
    from qa_eval.harness import LatencyMetrics
    m = LatencyMetrics()
    assert m.stt_p50 is None
    assert m.summary()["turns"] == 0
