"""Run qa-eval tests directly (avoids pytest hanging)."""
import sys
sys.path.insert(0, ".")

from qa_eval.harness import EvalCase, ExpectedField, QAEvalHarness, LatencyMetrics

harness = QAEvalHarness(backend_url="http://localhost:9999", api_token="test")

TRANSCRIPT = [
    {"speaker": "agent", "text": "Hello, I am an AI assistant calling from the university."},
    {"speaker": "user", "text": "Yes, this is Mrs. Sharma speaking."},
    {"speaker": "agent", "text": "Mrs. Sharma, I'm calling about your son Rahul's absence today."},
    {"speaker": "user", "text": "Rahul has a fever since yesterday."},
    {"speaker": "agent", "text": "When do you expect Rahul to return?"},
    {"speaker": "user", "text": "He should be back by Friday, August 29th."},
]

# T1: extraction pass
case = EvalCase(
    name="test-pass",
    agent_version_id=1,
    to_number="+917842594002",
    expected_fields=[
        ExpectedField("reason_for_absence", "fever"),
        ExpectedField("expected_return_date", "august 29"),
    ],
    simulated_transcript=TRANSCRIPT,
)
result = harness._run_simulated(case)
assert result.status == "pass", f"expected pass, got {result.status}"
assert result.extraction_accuracy == 1.0
print("T1 OK: extraction pass")

# T2: extraction fail
case2 = EvalCase(
    name="test-fail",
    agent_version_id=1,
    to_number="+917842594002",
    expected_fields=[ExpectedField("reason_for_absence", "dengue")],
    simulated_transcript=TRANSCRIPT,
)
result2 = harness._run_simulated(case2)
assert result2.status == "fail"
assert result2.extraction_accuracy == 0.0
print("T2 OK: extraction fail")

# T3: empty transcript
case3 = EvalCase(
    name="test-empty",
    agent_version_id=1,
    to_number="+917842594002",
    expected_fields=[ExpectedField("reason_for_absence", "fever")],
    simulated_transcript=[],
)
result3 = harness._run_simulated(case3)
assert result3.status == "fail"
print("T3 OK: empty transcript")

# T4: report generation
report = result.report()
assert "test-pass" in report
print("T4 OK: report generation")

# T5: latency metrics
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
print("T5 OK: latency metrics")

# T6: empty latency
m2 = LatencyMetrics()
assert m2.stt_p50 is None
print("T6 OK: empty latency")

print("\nALL 6 QA-EVAL TESTS PASS")
