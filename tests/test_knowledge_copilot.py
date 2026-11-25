import json
from pathlib import Path

from tokeneconomizer.knowledge.observation import observations
from tokeneconomizer.knowledge.proof import verify_file


FIXTURES = Path(__file__).parent / "fixtures" / "knowledge"


def replay(tmp_path, case):
    transcript = tmp_path / "session.jsonl"
    text = (FIXTURES / f"copilot-{case}.jsonl").read_text()
    transcript.write_text(text.replace("__WORKSPACE__", str(tmp_path)))
    return transcript


def test_actual_copilot_complete_view_attests_observed_content(tmp_path):
    transcript = replay(tmp_path, "complete")
    (tmp_path / "source.txt").write_text("changed\n")
    proof = observations(transcript, tmp_path, host="copilot")["source.txt"]["proof"]
    assert proof["sha256"] == "08cfb1f08c9a2b3985853df5336808a27d616d731c6e944ff0a4e8e74dde5e5f"


def test_actual_copilot_partial_and_large_reads_do_not_attest(tmp_path):
    for case in ("partial", "large"):
        assert observations(replay(tmp_path, case), tmp_path, host="copilot") == {}


def test_actual_copilot_preserves_unicode_and_crlf(tmp_path):
    transcript = replay(tmp_path, "unicode")
    (tmp_path / "source.txt").write_bytes("é🙂\r\nend\r\n".encode())
    proof = observations(transcript, tmp_path, host="copilot")["source.txt"]["proof"]
    assert verify_file(tmp_path, proof)


def test_copilot_without_truncation_telemetry_is_not_evidence(tmp_path):
    transcript = replay(tmp_path, "complete")
    events = [json.loads(x) for x in transcript.read_text().splitlines()]
    del events[-1]["data"]["toolTelemetry"]
    transcript.write_text("\n".join(map(json.dumps, events)))
    assert observations(transcript, tmp_path, host="copilot") == {}


def test_copilot_changed_version_or_model_truncation_is_not_evidence(tmp_path):
    transcript = replay(tmp_path, "complete")
    original = [json.loads(x) for x in transcript.read_text().splitlines()]
    for mutate in ("version", "truncated"):
        events = json.loads(json.dumps(original))
        if mutate == "version":
            events[0]["data"]["copilotVersion"] = "unknown"
        else:
            events[-1]["data"]["toolTelemetry"]["metrics"]["resultForLlmLength"] = 3
        transcript.write_text("\n".join(map(json.dumps, events)))
        assert observations(transcript, tmp_path, host="copilot") == {}


def test_corrupted_recording_cannot_attest_a_file(tmp_path):
    transcript = replay(tmp_path, "complete")
    with transcript.open("ab") as stream:
        stream.write(b"\n\xff\n")
    assert observations(transcript, tmp_path, host="copilot") == {}


def test_copilot_recorded_views_flow_through_hook(tmp_path, monkeypatch):
    from tests.test_live_hooks import call, run_session
    from tokeneconomizer.plugin import sidecall
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (repo / "source.txt").write_text("observed\n")
    (repo / "support.txt").write_text("observed\n")
    env = {"TOKENECONOMIZER_HOME": str(tmp_path / "home"), "TE_FOLD_SYNC": "1", "TE_KNOWLEDGE": "on", "TE_MICROSKILLS": "off", "TE_TOOLPRUNE": "off", "TE_LOOPGUARD": "off"}
    candidate = {"id": "k", "claim": "Copilot observation", "flow": "source and support", "sources": [{"source": "source.txt", "role": "source"}, {"source": "support.txt", "role": "support"}], "source_session": "s1", "cite": ["s0", "s1"], "detector": {"scope": "pytest", "confirm": "passed"}}
    monkeypatch.setattr(sidecall, "runner_for", lambda *a, **kw: lambda *a: (json.dumps({"facts": [candidate]}), 0))
    for i in range(5):
        transcript = tmp_path / f"s{i}.jsonl"
        text = (FIXTURES / "copilot-complete.jsonl").read_text().replace("__WORKSPACE__", str(repo))
        lines = text.splitlines()
        text += "\n" + "\n".join(line.replace("source.txt", "support.txt").replace("call_1", "call_2") for line in lines[1:]) + "\n"
        extra = [
            {"type": "user.message", "data": {"content": "check"}},
            {"type": "tool.execution_start", "data": {"toolCallId": "sh", "toolName": "bash", "arguments": {"command": "pytest"}}},
            {"type": "tool.execution_complete", "data": {"toolCallId": "sh", "success": True, "result": {"content": "passed"}}},
            {"type": "session.shutdown", "data": {}},
        ]
        transcript.write_text(text + "\n".join(map(json.dumps, extra)))
        run_session(env, str(repo), f"s{i}", str(transcript), host="copilot")
    start = {"hook_event_name": "SessionStart", "source": "new", "session_id": "next", "cwd": str(repo)}
    startup = call(env, start, host="copilot")["additionalContext"]
    assert "Copilot observation" in startup
    assert call(env, dict(start, source="resume"), host="copilot")["additionalContext"] == startup
    payload = dict(start, hook_event_name="UserPromptSubmit", prompt="explain source.txt")
    assert call(env, payload, host="copilot") == {}
    # A read of the covered file: top-level additionalContext, after the tool's result.
    read = {"hook_event_name": "PostToolUse", "session_id": "read", "cwd": str(repo), "tool_name": "Read",
            "tool_input": {"path": str(repo / "source.txt")}, "tool_result": {"text_result_for_llm": "observed\n"}}
    assert "Copilot observation" in call(env, read, host="copilot")["additionalContext"]
    assert call(env, read, host="copilot") == {}
    (repo / "source.txt").write_text("changed\n")
    assert "Copilot observation" not in json.dumps(call(env, dict(start, source="resume"), host="copilot"))
