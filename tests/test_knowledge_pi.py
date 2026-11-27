import json
from pathlib import Path

from tokeneconomizer.knowledge.observation import observations
from tokeneconomizer.knowledge.stage import Knowledge


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
    (repo / "support.txt").write_text("support\n")
    env = {"TOKENECONOMIZER_HOME": str(tmp_path / "home"), "TE_FOLD_SYNC": "1", "TE_KNOWLEDGE": "on", "TE_MICROSKILLS": "off", "TE_TOOLPRUNE": "off", "TE_LOOPGUARD": "off"}
    candidate = {"id": "k", "claim": "Pi observation",
                 "sources": [{"ref": "s1/0.0"}],
                 "detector": {"scope": "pytest", "confirm": "passed"}}
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
            f.write("\n" + json.dumps({"type": "message", "id": "x", "parentId": "474c3ba4", "message": {"role": "assistant", "content": [{"type": "toolCall", "id": "other", "name": "read", "arguments": {"path": "support.txt"}}]}}))
            f.write("\n" + json.dumps({"type": "message", "id": "y", "parentId": "x", "message": {"role": "toolResult", "toolCallId": "other", "toolName": "read", "isError": False, "content": [{"type": "text", "text": "support\n"}]}}))
            f.write("\n" + json.dumps({"type": "message", "id": "c", "parentId": "y", "message": {"role": "assistant", "content": [{"type": "toolCall", "id": "t", "name": "bash", "arguments": {"command": "pytest"}}]}}))
            f.write("\n" + json.dumps({"type": "message", "id": "d", "parentId": "c", "message": {"role": "toolResult", "toolCallId": "t", "toolName": "bash", "isError": False, "content": [{"type": "text", "text": "passed"}]}}))
        run_session(env, str(repo), f"s{i}", str(transcript), host="pi")
        stage = Knowledge.load(workspace_id(ctx.repo.label, str(repo)), ctx.mech_dir)
        stage.workspace = repo
        counts.append((len(stage.facts), int("Pi observation" in stage.render())))
    # Admitted on the fold that proposes it, and injectable at once: no confirmation to earn.
    assert counts == [(0, 0), (1, 1), (1, 1), (1, 1), (1, 1)]
    start = {"hook_event_name": "SessionStart", "source": "startup", "session_id": "next", "cwd": str(repo)}
    assert "Pi observation" in call(env, start, host="pi")["hookSpecificOutput"]["additionalContext"]
    payload = dict(start, hook_event_name="UserPromptSubmit", prompt="explain source.txt")
    assert call(env, payload, host="pi") == {}
    assert call(env, dict(payload, session_id="other", prompt="rename widget"), host="pi") == {}
    # A read of the covered file: the extension sends it as a steering message after the result.
    read = {"hook_event_name": "PostToolUse", "session_id": "read", "cwd": str(repo), "tool_name": "read",
            "tool_input": {"path": "source.txt"}, "tool_response": {"content": "observed\nsecond\n", "isError": False}}
    assert call(env, dict(read, tool_response={"content": "read failed", "isError": True}),
                host="pi") == {}
    assert "Pi observation" in call(env, read, host="pi")["hookSpecificOutput"]["additionalContext"]
    assert call(env, read, host="pi") == {}
    from tokeneconomizer.plugin import cli
    fid = next(iter(Knowledge.load(workspace_id(ctx.repo.label, str(repo)), ctx.mech_dir).facts))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    def command(action):
        return cli.main(["--host", "pi", "--cwd", str(repo), "microskills", action, fid])
    assert command("forget") == 0
    assert "Pi observation" not in json.dumps(call(env, dict(read, session_id="forgotten"), host="pi"))
    (repo / "source.txt").unlink()
    assert command("unforget") == 0
    assert "Pi observation" not in json.dumps(call(env, dict(read, session_id="later"), host="pi"))
    (repo / "source.txt").write_text("observed\nsecond\n")
    assert "Pi observation" in json.dumps(call(env, dict(read, session_id="restored"), host="pi"))


# ---- partial reads, captured at the instant they returned --------------------------------
STATE = "state"


def pi_read(data, offset=None, limit=None, max_lines=2000):
    """The exact text Pi 1.6.0's `read` returns for these arguments over `data`."""
    lines = data.decode("utf-8").split("\n")
    start = 1 if offset is None else offset
    wanted = max_lines if limit is None else min(limit, max_lines)
    end = min(len(lines), start - 1 + wanted)
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


def reads_session(path, root, reads, bash=None, details=None,
                  message="Work on the files.", stamp="2026-11-24T10:00:00.000Z"):
    """A Pi session log: one real user message, then an assistant turn per (id, args) and its
    tool result. The message opens the session's first work sequence, so the reads are its
    first units (`<iid>/0.0`, `<iid>/0.1`...)."""
    entries = [{"type": "session", "version": 3, "id": "s", "cwd": str(root)},
               {"type": "message", "id": "p", "parentId": None, "timestamp": stamp,
                "message": {"role": "user", "content": [{"type": "text", "text": message}]}}]
    parent = "p"
    for i, (call_id, args, text, failed) in enumerate(reads):
        call = {"type": "message", "id": f"a{i}", "parentId": parent,
                "message": {"role": "assistant", "content": [
                    {"type": "toolCall", "id": call_id, "name": "read", "arguments": args}]}}
        result = {"type": "message", "id": f"b{i}", "parentId": f"a{i}",
                  "message": {"role": "toolResult", "toolCallId": call_id, "toolName": "read",
                              "isError": failed, "details": details,
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
    (repo / "support.txt").write_text("support\n")
    env = {"TOKENECONOMIZER_HOME": str(tmp_path / "home"), "TE_FOLD_SYNC": "1",
           "TE_KNOWLEDGE": "on", "TE_MICROSKILLS": "off", "TE_TOOLPRUNE": "off",
           "TE_LOOPGUARD": "off"}
    candidate = {"id": "k", "claim": "Alpha returns one",
                 "sources": [{"ref": "s1/0.0", "symbol": "alpha"}],
                 "detector": {"scope": "pytest", "confirm": "passed"}}
    monkeypatch.setattr(sidecall, "runner_for",
                        lambda *a, **kw: lambda *a: (json.dumps({"facts": [candidate]}), 0))
    ctx = LiveContext.build(Pi(), str(repo), env)
    args, text = {"path": "source.py", "offset": 2, "limit": 1}, pi_read(SOURCE, 2, 1)
    for i in range(5):
        transcript = tmp_path / f"s{i}.jsonl"
        reads_session(transcript, repo, [("r", args, text, False), ("support", {"path": "support.txt"}, "support\n", False)],
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
    assert next(iter(stage.facts.values())).spec["proof"][0]["kind"] == "symbol"
    assert "Alpha returns one" in stage.render()
    start = {"hook_event_name": "PostToolUse", "cwd": str(repo), "tool_name": "read",
             "tool_input": {"path": "source.py"}, "tool_response": {"content": "observed"}}
    assert "Alpha returns one" in json.dumps(call(env, dict(start, session_id="next"), host="pi"))
    # the symbol's unread line, a comment inside it, and the rest of the file
    (repo / "source.py").write_bytes(SOURCE.replace(b"    return 1", b"    return 9"))
    assert "Alpha returns one" not in json.dumps(call(env, dict(start, session_id="edited"), host="pi"))
    (repo / "source.py").write_bytes(SOURCE.replace(b"    return 1", b"    # why\n    return 1"))
    assert "Alpha returns one" in json.dumps(call(env, dict(start, session_id="comment"), host="pi"))
    (repo / "source.py").write_bytes(SOURCE)
    assert "Alpha returns one" in json.dumps(call(env, dict(start, session_id="restored"), host="pi"))


def test_a_read_pi_truncated_is_observable_through_its_capture(tmp_path):
    data = "".join(f"line {i}\n" for i in range(1, 3001)).encode("utf-8")
    source = tmp_path / "big.py"
    source.write_bytes(data)
    args, text = {"path": "big.py", "offset": 1, "limit": 5000}, pi_read(data, 1, 5000)
    assert text.endswith("[Showing lines 1-2000 of 3001. Use offset=2001 to continue.]")
    path = tmp_path / "session.jsonl"
    reads_session(path, tmp_path, [("r", args, text, False)],
                  details={"truncation": {"truncated": True}})
    captures = capture_read(tmp_path, args, text)
    record = observations(path, tmp_path, host="pi", captures=captures)["big.py"]
    assert record["partial"] is True
    assert record["observed"] == {"reads": [{"offset": 1, "lines": 2000}], "total_lines": 3001}


def test_a_capture_that_raises_keeps_the_hook_answer_and_the_guard(tmp_path, monkeypatch):
    """A capture failure is a line in `errors.log`, as for any hook, not a lost answer."""
    from tests.test_live_hooks import call, store_for
    from tokeneconomizer.knowledge import capture
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (repo / "source.py").write_bytes(SOURCE)
    home = tmp_path / "home"
    env = {"TOKENECONOMIZER_HOME": str(home), "TE_KNOWLEDGE": "on",
           "TE_MICROSKILLS": "off", "TE_LOOPGUARD": "on", "TE_TOOLPRUNE": "off"}
    args, text = {"path": "source.py", "offset": 2, "limit": 1}, pi_read(SOURCE, 2, 1)

    def payload(session_id):
        return {"hook_event_name": "PostToolUse", "session_id": session_id,
                "prompt_id": "p1", "transcript_path": "", "cwd": str(repo),
                "tool_name": "read", "tool_use_id": "r", "tool_input": args,
                "tool_response": {"content": text, "isError": False}}

    expected = call(env, payload("capturing"), host="pi")

    def boom(*args, **kwargs):
        raise RuntimeError("capture bug")

    monkeypatch.setattr(capture, "_record", boom)
    assert call(env, payload("broken"), host="pi") == expected
    # the guard still folded and saved the call: only the capture was lost
    state = store_for(env, str(repo), host="pi").read("sessions/broken.json")
    assert state["turn"]["cum_turns"] == 1
    log = (home / "errors.log").read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in log
    assert "RuntimeError: capture bug" in log


def test_partial_reads_of_two_versions_of_a_file_do_not_merge():
    from tokeneconomizer.knowledge.observation import _merge_read

    def read(version, offset):
        return {"record": {"partial": True, "version": version, "symbols": {version: {}},
                           "observed": {"reads": [{"offset": offset, "lines": 1}], "total_lines": 7}}}
    same = _merge_read(read("v1", 1)["record"], read("v1", 4))
    assert sorted(same["symbols"]) == ["v1"] and len(same["observed"]["reads"]) == 2
    changed = _merge_read(read("v1", 1)["record"], read("v2", 4))
    assert sorted(changed["symbols"]) == ["v2"]
    assert changed["observed"]["reads"] == [{"offset": 4, "lines": 1}]


# ---- the digest on Pi: real messages, the active branch, one sequence each ------------------
def pi_session(root, turns):
    """A Pi session log on one branch: `turns` is [(stamp, message, reads)], where `message` is
    the entry-level `message` dict to write (None for none) and `reads` are the reads it made,
    `(call_id, args, text, failed)`."""
    entries = [{"type": "session", "version": 3, "id": "s", "cwd": str(root)}]
    parent, n = None, 0
    for stamp, message, reads in turns:
        if message is not None:
            entry = {"type": "message", "id": f"m{n}", "parentId": parent,
                     "message": message}
            if stamp:
                entry["timestamp"] = stamp
            entries.append(entry)
            parent, n = entry["id"], n + 1
        for call_id, args, text, failed in reads:
            entries += [
                {"type": "message", "id": f"a{n}", "parentId": parent,
                 "message": {"role": "assistant", "content": [
                     {"type": "toolCall", "id": call_id, "name": "read",
                      "arguments": args}]}},
                {"type": "message", "id": f"b{n}", "parentId": f"a{n}",
                 "message": {"role": "toolResult", "toolCallId": call_id, "toolName": "read",
                             "isError": failed,
                             "content": [{"type": "text", "text": text}]}}]
            parent, n = f"b{n}", n + 1
    return entries


def pi_digest(stage):
    """Write the session's log and return the digest its proposer is shown."""
    from tests.fixtures import knowledge_digest
    prompts = []
    stage.runner = lambda prompt, model: (prompts.append(prompt) or '{"facts": []}', 0)
    stage._maybe_propose()
    return knowledge_digest(prompts[0])


def test_a_recorded_pi_request_opens_the_first_sequence(tmp_path):
    fixtures = Path(__file__).parent / "fixtures" / "knowledge"
    transcript = tmp_path / "complete.jsonl"
    transcript.write_text((fixtures / "pi-complete.jsonl").read_text()
                          .replace("__WORKSPACE__", str(tmp_path)))
    (tmp_path / "source.txt").write_text("observed\nsecond\n")
    stage = Knowledge("repo")
    stage.workspace, stage.host = tmp_path, "pi"
    stage.update(transcript, iid="s0")
    view = pi_digest(stage)
    # The recording's own `system` message opens nothing; its one real prompt does.
    assert [(s["id"], s["message"], s["refs"]) for s in view["sequences"]] == [
        ("s0/0", "Read source.txt and finish.", ["s0/0.0"])]
    assert [(e["ref"], e["path"], len(e["version"])) for e in view["excerpts"]] == [
        ("s0/0.0", "source.txt", 12)]


def test_pi_injected_and_system_messages_open_no_work_sequence(tmp_path):
    (tmp_path / "source.txt").write_text("observed\n")
    path = tmp_path / "pi.jsonl"
    path.write_text("\n".join(map(json.dumps, pi_session(tmp_path, [
        ("2026-11-24T10:00:00.000Z", {"role": "system", "content": ""}, []),
        ("2026-11-24T10:00:01.000Z",
         {"role": "custom", "customType": "tokeneconomizer",
          "content": [{"type": "text", "text": "steering after a read"}]}, []),
        ("2026-11-24T10:00:02.000Z",
         {"role": "user", "content": [{"type": "text", "text": "read source.txt"}]},
         [("r", {"path": "source.txt"}, "observed\n", False)]),
    ]))))
    stage = Knowledge("repo")
    stage.workspace, stage.host = tmp_path, "pi"
    stage.update(path, iid="s0")
    view = pi_digest(stage)
    assert [(s["id"], s["message"], s["refs"]) for s in view["sequences"]] == [
        ("s0/0", "read source.txt", ["s0/0.0"])]


def test_pi_follows_the_active_branch_only(tmp_path):
    """An abandoned exchange stays in the log; its message opens no sequence."""
    (tmp_path / "first.txt").write_text("first\n")
    (tmp_path / "second.txt").write_text("second\n")
    (tmp_path / "abandoned.txt").write_text("abandoned\n")
    path = tmp_path / "pi.jsonl"
    entries = pi_session(tmp_path, [
        ("2026-11-24T10:00:00.000Z",
         {"role": "user", "content": [{"type": "text", "text": "read first.txt"}]},
         [("r1", {"path": "first.txt"}, "first\n", False)]),
        ("2026-11-24T10:01:00.000Z",
         {"role": "user", "content": [{"type": "text", "text": "read second.txt"}]},
         [("r2", {"path": "second.txt"}, "second\n", False)]),
    ])
    # An abandoned request hangs off the first result: the active branch never reaches it.
    entries.insert(-2, {"type": "message", "id": "gone", "parentId": "b1",
                        "timestamp": "2026-11-24T10:00:30.000Z",
                        "message": {"role": "user", "content": [
                            {"type": "text", "text": "read abandoned.txt"}]}})
    path.write_text("\n".join(map(json.dumps, entries)))
    stage = Knowledge("repo")
    stage.workspace, stage.host = tmp_path, "pi"
    stage.update(path, iid="s0")
    view = pi_digest(stage)
    assert [(s["id"], s["message"]) for s in view["sequences"]] == [
        ("s0/0", "read first.txt"), ("s0/1", "read second.txt")]
    assert [e["path"] for e in view["excerpts"]] == ["first.txt", "second.txt"]


def test_a_pi_request_naming_an_issue_or_a_skill_is_an_ordinary_request(tmp_path):
    (tmp_path / "source.txt").write_text("observed\n")
    path = tmp_path / "pi.jsonl"
    path.write_text("\n".join(map(json.dumps, pi_session(tmp_path, [
        ("2026-11-24T10:00:00.000Z",
         {"role": "user", "content": [{"type": "text",
                                       "text": "fix #123 with /codetour"}]},
         [("r", {"path": "source.txt"}, "observed\n", False)]),
    ]))))
    stage = Knowledge("repo")
    stage.workspace, stage.host = tmp_path, "pi"
    stage.update(path, iid="s0")
    view = pi_digest(stage)
    assert [(s["id"], s["message"], s["refs"]) for s in view["sequences"]] == [
        ("s0/0", "fix #123 with /codetour", ["s0/0.0"])]
