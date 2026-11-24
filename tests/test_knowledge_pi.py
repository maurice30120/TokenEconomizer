import json
from pathlib import Path

from tokeneconomizer.knowledge.observation import observations


def test_real_pi_session_recordings(tmp_path):
    fixtures = Path(__file__).parent / "fixtures" / "knowledge"
    for case in ("complete", "partial", "large"):
        transcript = tmp_path / f"{case}.jsonl"
        transcript.write_text((fixtures / f"pi-{case}.jsonl").read_text().replace("__WORKSPACE__", str(tmp_path)))
        found = observations(transcript, tmp_path, host="pi")
        assert ("source.txt" in found) == (case == "complete")


def session(path, root, args, output, *, details=None, failed=False):
    entries = [
        {"type": "session", "version": 3, "id": "s", "cwd": str(root)},
        {"type": "message", "id": "a", "parentId": None, "message": {"role": "assistant", "content": [{"type": "toolCall", "id": "r", "name": "read", "arguments": args}]}},
        {"type": "message", "id": "b", "parentId": "a", "message": {"role": "toolResult", "toolCallId": "r", "toolName": "read", "isError": failed, "details": details, "content": [{"type": "text", "text": output}]}},
    ]
    path.write_text("\n".join(map(json.dumps, entries)))


def test_pi_complete_read_uses_bytes_observed_before_file_changes(tmp_path):
    path = tmp_path / "session.jsonl"
    session(path, tmp_path, {"path": "source.txt"}, "old version\n")
    (tmp_path / "source.txt").write_text("changed\n")
    found = observations(path, tmp_path, host="pi")
    assert found["source.txt"]["proof"]["sha256"] == "6e7b43edb0cd439076a2dab27515ed5d563dda0acc5639ae1f6c922d92d7871c"


def test_pi_rejects_partial_failed_and_truncated_results(tmp_path):
    path = tmp_path / "session.jsonl"
    for args, text, details, failed in [
        ({"path": "source.txt", "offset": 1}, "partial", None, False),
        ({"path": "source.txt", "limit": 1}, "partial", None, False),
        ({"path": "source.txt"}, "partial", {"truncation": {"truncated": True}}, False),
        ({"path": "source.txt"}, "partial\n\n[Showing lines 1-1 of 2. Use offset=2 to continue.]", None, False),
        ({"path": "source.txt"}, "partial", None, True),
        ({"path": "source.txt"}, "invalid \ufffd bytes", None, False),
    ]:
        session(path, tmp_path, args, text, details=details, failed=failed)
        assert observations(path, tmp_path, host="pi") == {}


def test_pi_hook_learns_from_recorded_active_sessions(tmp_path, monkeypatch):
    from tests.test_live_hooks import call, run_session
    fixtures = Path(__file__).parent / "fixtures" / "knowledge"
    from tokeneconomizer.plugin import sidecall
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (repo / "source.txt").write_text("observed\nsecond\n")
    env = {"TOKENECONOMIZER_HOME": str(tmp_path / "home"), "TE_FOLD_SYNC": "1", "TE_KNOWLEDGE": "on", "TE_MICROSKILLS": "off", "TE_TOOLPRUNE": "off", "TE_LOOPGUARD": "off"}
    candidate = {"id": "k", "claim": "Pi observation", "source": "source.txt", "source_session": "s1", "cite": ["s0", "s1"], "detector": {"scope": "pytest", "confirm": "passed"}}
    monkeypatch.setattr(sidecall, "runner_for", lambda *a, **kw: lambda *a: (json.dumps({"facts": [candidate]}), 0))
    counts = []
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import Pi
    from tokeneconomizer.knowledge.stage import Knowledge, workspace_id
    ctx = LiveContext.build(Pi(), str(repo), env)
    for i in range(5):
        transcript = tmp_path / f"s{i}.jsonl"
        transcript.write_text((fixtures / "pi-complete.jsonl").read_text().replace("__WORKSPACE__", str(repo)))
        with transcript.open("a") as f:
            f.write("\n" + json.dumps({"type": "message", "id": "c", "parentId": "474c3ba4", "message": {"role": "assistant", "content": [{"type": "toolCall", "id": "t", "name": "bash", "arguments": {"command": "pytest"}}]}}))
            f.write("\n" + json.dumps({"type": "message", "id": "d", "parentId": "c", "message": {"role": "toolResult", "toolCallId": "t", "toolName": "bash", "isError": False, "content": [{"type": "text", "text": "passed"}]}}))
        run_session(env, str(repo), f"s{i}", str(transcript), host="pi")
        stage = Knowledge.load(workspace_id(ctx.repo.label, str(repo)), ctx.mech_dir)
        stage.workspace = repo
        counts.append((len(stage.facts), int("Pi observation" in stage.render())))
    assert counts == [(0, 0), (1, 0), (1, 0), (1, 1), (1, 1)]
    payload = {"hook_event_name": "SessionStart", "source": "startup", "session_id": "next", "cwd": str(repo)}
    assert "Pi observation" in json.dumps(call(env, payload, host="pi"))
    from tokeneconomizer.plugin import cli
    fid = next(iter(Knowledge.load(workspace_id(ctx.repo.label, str(repo)), ctx.mech_dir).facts))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    def command(action):
        return cli.main(["--host", "pi", "--cwd", str(repo), "microskills", action, fid])
    assert command("forget") == 0
    assert "Pi observation" not in json.dumps(call(env, dict(payload, session_id="forgotten"), host="pi"))
    (repo / "source.txt").unlink()
    assert command("unforget") == 0
    assert "Pi observation" not in json.dumps(call(env, dict(payload, session_id="later"), host="pi"))
    (repo / "source.txt").write_text("observed\nsecond\n")
    assert "Pi observation" in json.dumps(call(env, dict(payload, session_id="restored"), host="pi"))
