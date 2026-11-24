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


# ---- partial reads, captured at the instant they returned --------------------------------
STATE = "state"


def pi_read(data, offset=None, limit=None, max_lines=2000):
    """The exact text Pi 1.6.0's `read` returns for these arguments over `data`."""
    lines = data.decode("utf-8").split("\n")
    start = 1 if offset is None else offset
    end = min(len(lines), start - 1 + (max_lines if limit is None else limit))
    body = "\n".join(lines[start - 1:end])
    rest = len(lines) - end
    if rest <= 0:
        return body
    if limit is not None and end == start - 1 + limit:
        return body + f"\n\n[{rest} more lines in file. Use offset={end + 1} to continue.]"
    return (body + f"\n\n[Showing lines {start}-{end} of {len(lines)}. "
            f"Use offset={end + 1} to continue.]")


def capture_read(root, args, text, tool_use_id="r", session_id="s"):
    """What the PostToolUse hook writes for one read; returns the session's capture directory."""
    from types import SimpleNamespace
    from tokeneconomizer.knowledge.capture import record, session_dir
    from tokeneconomizer.plugin.store import Store
    store = Store(str(root / STATE))
    record(store, session_id, SimpleNamespace(repo=SimpleNamespace(root=str(root))),
           {"hook_event_name": "PostToolUse", "session_id": session_id, "tool_name": "read",
            "tool_use_id": tool_use_id, "tool_input": args,
            "tool_response": {"content": text, "isError": False}})
    return session_dir(store, session_id)


def reads_session(path, root, reads, bash=None):
    """A Pi session log: one assistant turn per (id, args) and its tool result."""
    entries = [{"type": "session", "version": 3, "id": "s", "cwd": str(root)}]
    parent = None
    for i, (call_id, args, text, failed) in enumerate(reads):
        call = {"type": "message", "id": f"a{i}", "parentId": parent,
                "message": {"role": "assistant", "content": [
                    {"type": "toolCall", "id": call_id, "name": "read", "arguments": args}]}}
        result = {"type": "message", "id": f"b{i}", "parentId": f"a{i}",
                  "message": {"role": "toolResult", "toolCallId": call_id, "toolName": "read",
                              "isError": failed, "details": None,
                              "content": [{"type": "text", "text": text}]}}
        entries += [call, result]
        parent = f"b{i}"
    if bash:
        entries += [
            {"type": "message", "id": "c", "parentId": parent,
             "message": {"role": "assistant", "content": [
                 {"type": "toolCall", "id": "t", "name": "bash",
                  "arguments": {"command": bash[0]}}]}},
            {"type": "message", "id": "d", "parentId": "c",
             "message": {"role": "toolResult", "toolCallId": "t", "toolName": "bash",
                         "isError": False, "content": [{"type": "text", "text": bash[1]}]}}]
    path.write_text("\n".join(map(json.dumps, entries)))


SOURCE = b"def alpha():\n    return 1\n\ndef beta():\n    # beta marker\n    return 2\n"


def test_a_partial_read_proves_the_symbol_it_crossed(tmp_path):
    from tokeneconomizer.knowledge.capture import load
    source = tmp_path / "source.py"
    source.write_bytes(SOURCE)
    args, text = {"path": "source.py", "offset": 2, "limit": 1}, pi_read(SOURCE, 2, 1)
    path = tmp_path / "session.jsonl"
    reads_session(path, tmp_path, [("r", args, text, False)])
    captures = capture_read(tmp_path, args, text)
    found = observations(path, tmp_path, host="pi", captures=captures)
    record = found["source.py"]
    assert "proof" not in record and record is not None
    assert record["partial"] is True
    assert sorted(record["symbols"]) == ["alpha"]
    assert record["symbols"]["alpha"]["kind"] == "symbol"
    assert record["observed"] == {"reads": [{"offset": 2, "lines": 1}], "total_lines": 7}
    # the part that was never read is not presented as observed
    assert record["content"] == "    return 1"
    assert "beta marker" not in json.dumps(record)
    assert load(captures)["r"]["bytes"] == SOURCE


def test_a_partial_read_without_its_capture_is_not_an_observation(tmp_path):
    source = tmp_path / "source.py"
    source.write_bytes(SOURCE)
    args, text = {"path": "source.py", "offset": 2, "limit": 1}, pi_read(SOURCE, 2, 1)
    path = tmp_path / "session.jsonl"
    reads_session(path, tmp_path, [("r", args, text, False)])
    assert observations(path, tmp_path, host="pi") == {}
    assert observations(path, tmp_path, host="pi",
                        captures=tmp_path / "missing") == {}


def test_a_capture_of_another_version_proves_nothing(tmp_path):
    source = tmp_path / "source.py"
    old = SOURCE
    source.write_bytes(old)
    args, text = {"path": "source.py", "offset": 2, "limit": 1}, pi_read(old, 2, 1)
    captures = capture_read(tmp_path, args, text)
    source.write_bytes(old.replace(b"return 1", b"return 4"))
    path = tmp_path / "session.jsonl"
    reads_session(path, tmp_path, [("r", args, pi_read(source.read_bytes(), 2, 1), False)])
    assert observations(path, tmp_path, host="pi", captures=captures) == {}


def test_a_capture_outside_the_workspace_proves_nothing(tmp_path):
    source = tmp_path / "source.py"
    source.write_bytes(SOURCE)
    args, text = {"path": "source.py", "offset": 2, "limit": 1}, pi_read(SOURCE, 2, 1)
    captures = Path(capture_read(tmp_path, args, text))
    index = json.loads((captures / "index.json").read_text())
    index["captures"][0]["path"] = "../source.py"
    (captures / "index.json").write_text(json.dumps(index))
    path = tmp_path / "session.jsonl"
    reads_session(path, tmp_path, [("r", args, text, False)])
    assert observations(path, tmp_path, host="pi", captures=str(captures)) == {}


def test_a_failed_read_never_becomes_an_observation(tmp_path):
    source = tmp_path / "source.py"
    source.write_bytes(SOURCE)
    args, text = {"path": "source.py", "offset": 2, "limit": 1}, pi_read(SOURCE, 2, 1)
    captures = capture_read(tmp_path, args, text)
    path = tmp_path / "session.jsonl"
    reads_session(path, tmp_path, [("r", args, text, True)])
    assert observations(path, tmp_path, host="pi", captures=captures) == {}


def test_two_partial_reads_of_one_file_merge_their_symbols_and_ranges(tmp_path):
    source = tmp_path / "source.py"
    source.write_bytes(SOURCE)
    first = {"path": "source.py", "offset": 2, "limit": 1}
    second = {"path": "source.py", "offset": 6, "limit": 1}
    path = tmp_path / "session.jsonl"
    reads_session(path, tmp_path, [("a", first, pi_read(SOURCE, 2, 1), False),
                                   ("b", second, pi_read(SOURCE, 6, 1), False)])
    captures = capture_read(tmp_path, first, pi_read(SOURCE, 2, 1), tool_use_id="a")
    assert capture_read(tmp_path, second, pi_read(SOURCE, 6, 1), tool_use_id="b") == captures
    record = observations(path, tmp_path, host="pi", captures=captures)["source.py"]
    assert sorted(record["symbols"]) == ["alpha", "beta"]
    assert record["observed"] == {"reads": [{"offset": 2, "lines": 1},
                                            {"offset": 6, "lines": 1}], "total_lines": 7}


def test_a_complete_read_replaces_an_earlier_partial_one(tmp_path):
    source = tmp_path / "source.py"
    source.write_bytes(SOURCE)
    first = {"path": "source.py", "offset": 2, "limit": 1}
    whole = {"path": "source.py", "offset": 1, "limit": 99}
    path = tmp_path / "session.jsonl"
    reads_session(path, tmp_path, [("a", first, pi_read(SOURCE, 2, 1), False),
                                   ("b", whole, pi_read(SOURCE, 1, 99), False)])
    captures = capture_read(tmp_path, first, pi_read(SOURCE, 2, 1), tool_use_id="a")
    capture_read(tmp_path, whole, pi_read(SOURCE, 1, 99), tool_use_id="b")
    record = observations(path, tmp_path, host="pi", captures=captures)["source.py"]
    assert record.get("partial") is None and record["content"] == SOURCE.decode()
    assert record["proof"]["sha256"]


def test_a_partial_read_that_covers_the_file_is_a_complete_observation(tmp_path):
    source = tmp_path / "source.py"
    source.write_bytes(SOURCE)
    args, text = {"path": "source.py", "offset": 1, "limit": 99}, pi_read(SOURCE, 1, 99)
    path = tmp_path / "session.jsonl"
    reads_session(path, tmp_path, [("r", args, text, False)])
    captures = capture_read(tmp_path, args, text)
    record = observations(path, tmp_path, host="pi", captures=captures)["source.py"]
    assert record.get("partial") is None
    assert record["content"] == SOURCE.decode()


def test_a_pi_partial_read_reaches_the_fold_creates_and_invalidates_knowledge(tmp_path, monkeypatch):
    from tests.test_live_hooks import call, run_session
    from tokeneconomizer.knowledge.capture import load, session_dir
    from tokeneconomizer.knowledge.stage import Knowledge, workspace_id
    from tokeneconomizer.plugin import sidecall
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import Pi
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (repo / "source.py").write_bytes(SOURCE)
    env = {"TOKENECONOMIZER_HOME": str(tmp_path / "home"), "TE_FOLD_SYNC": "1",
           "TE_KNOWLEDGE": "on", "TE_MICROSKILLS": "off", "TE_TOOLPRUNE": "off",
           "TE_LOOPGUARD": "off"}
    candidate = {"id": "k", "claim": "Alpha returns one", "source": "source.py",
                 "symbol": "alpha", "source_session": "s1", "cite": ["s0", "s1"],
                 "detector": {"scope": "pytest", "confirm": "passed"}}
    monkeypatch.setattr(sidecall, "runner_for",
                        lambda *a, **kw: lambda *a: (json.dumps({"facts": [candidate]}), 0))
    ctx = LiveContext.build(Pi(), str(repo), env)
    args, text = {"path": "source.py", "offset": 2, "limit": 1}, pi_read(SOURCE, 2, 1)
    for i in range(5):
        transcript = tmp_path / f"s{i}.jsonl"
        reads_session(transcript, repo, [("r", args, text, False)],
                      bash=("pytest", "1 passed"))
        call(env, {"hook_event_name": "PostToolUse", "session_id": f"s{i}",
                   "transcript_path": str(transcript), "cwd": str(repo),
                   "tool_name": "read", "tool_use_id": "r", "tool_input": args,
                   "tool_response": {"content": text, "isError": False}}, host="pi")
        captures = session_dir(ctx.store, f"s{i}")
        assert load(captures)["r"]["bytes"] == SOURCE
        run_session(env, str(repo), f"s{i}", str(transcript), host="pi")
        assert load(captures) == {}, "the fold takes the capture and removes it"
    stage = Knowledge.load(workspace_id(ctx.repo.label, str(repo)), ctx.mech_dir)
    stage.workspace, stage.host = repo, "pi"
    assert len(stage.facts) == 1
    assert next(iter(stage.facts.values())).spec["proof"]["kind"] == "symbol"
    assert "Alpha returns one" in stage.render()
    start = {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(repo)}
    assert "Alpha returns one" in json.dumps(call(env, dict(start, session_id="next"), host="pi"))
    # the symbol's unread line, a comment inside it, and the rest of the file
    (repo / "source.py").write_bytes(SOURCE.replace(b"    return 1", b"    return 9"))
    assert "Alpha returns one" not in json.dumps(call(env, dict(start, session_id="edited"), host="pi"))
    (repo / "source.py").write_bytes(SOURCE.replace(b"    return 1", b"    # why\n    return 1"))
    assert "Alpha returns one" in json.dumps(call(env, dict(start, session_id="comment"), host="pi"))
    (repo / "source.py").write_bytes(SOURCE)
    assert "Alpha returns one" in json.dumps(call(env, dict(start, session_id="restored"), host="pi"))
