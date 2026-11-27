import json
from pathlib import Path

import pytest

from tokeneconomizer.knowledge.stage import Knowledge, workspace_id
from tokeneconomizer.plugin.config import load_config
from tests.test_knowledge_pi import SOURCE, capture_read, pi_read, reads_session
from tests.test_live_hooks import call, env, repo, run_session  # noqa: F401


def test_knowledge_is_independent_and_disabled_by_default(tmp_path):
    assert not load_config(str(tmp_path), env={}).knowledge
    cfg = load_config(str(tmp_path), env={"TE_KNOWLEDGE": "on", "TE_MICROSKILLS": "off"})
    assert cfg.knowledge and cfg.microskills == "off"


def claude_prompt(text, stamp="2026-11-24T10:00:00.000Z"):
    """A real user message, as Claude Code writes one."""
    return {"type": "user", "timestamp": stamp,
            "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def fold_session(stage, tmp_path, i, names=("source.txt",), command="pytest",
                 output="passed"):
    """Fold one Claude session whose request read each of `names` completely and ran
    `command`; its reads are the units `s<i>/0.0`, `s<i>/0.1`... of sequence `s<i>/0`."""
    uses, results = [], []
    for n, name in enumerate(names):
        content = (tmp_path / name).read_text()
        lines = len(content.splitlines())
        uses.append({"type": "tool_use", "id": f"r{n}", "name": "Read",
                     "input": {"file_path": str(tmp_path / name)}})
        results.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"r{n}", "content": content}]},
            "toolUseResult": {"type": "text", "file": {
                "filePath": str(tmp_path / name), "content": content,
                "startLine": 1, "numLines": lines, "totalLines": lines}}})
    uses.append({"type": "tool_use", "id": "sh", "name": "Bash",
                 "input": {"command": command}})
    events = [claude_prompt("work on " + ", ".join(names)),
              {"type": "assistant", "message": {"content": uses}}, *results,
              {"type": "user", "message": {"content": [
                  {"type": "tool_result", "tool_use_id": "sh", "content": output}]}}]
    path = tmp_path / f"fold{i}.jsonl"
    path.write_text("\n".join(map(json.dumps, events)))
    stage.update(path, iid=f"s{i}")


def observed_stage(tmp_path, names=("source.txt",), sessions=1):
    """A `Knowledge` whose window holds a complete read of each of `names`, plus a passing
    pytest run, for each of `sessions` sessions (the host is Claude)."""
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    for i in range(sessions):
        fold_session(stage, tmp_path, i, names)
    return stage


def test_one_complete_read_admits_and_injects_a_knowledge_in_the_same_cycle(tmp_path):
    (tmp_path / "source.txt").write_text("observed\n")
    stage = observed_stage(tmp_path)
    assert stage.render() == ""
    assert stage._admit({
        "id": "k", "claim": "Source is observed",
        "injection": "source.txt holds the observed value",
        "sources": [{"ref": "s0/0.0"}],
        "detector": {"scope": "pytest", "confirm": "passed"}}) == (True, "admitted")
    fact = next(iter(stage.facts.values()))
    assert set(fact.spec) == {"id", "claim", "injection", "detector", "rev", "proof",
                              "provenance"}
    assert (fact.spec["rev"], fact.state) == (1, "ACTIVE")
    assert [proof["path"] for proof in fact.spec["proof"]] == ["source.txt"]
    assert fact.spec["provenance"] == {"sources": [{"path": "source.txt", "session": "s0"}]}
    assert "source.txt holds the observed value" in stage.render()


def test_one_observed_read_is_proposed_admitted_and_injected_in_the_next_cycle(
        tmp_path, env, repo, monkeypatch):
    """The whole journey on one source: a session reads one file, the next fold proposes it on
    the shared cadence, admission is immediate, and the card reaches the next read."""
    from tokeneconomizer.plugin import sidecall
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    source = Path(repo) / "source.txt"
    source.write_text("observed\n")
    candidate = {"id": "k", "claim": "Source is observed",
                 "sources": [{"ref": "s0/0.0"}],
                 "detector": {"scope": "pytest", "confirm": "passed"}}
    prompts = []

    def runner(prompt, model):
        prompts.append(prompt)
        return json.dumps({"facts": [candidate]}), 0

    monkeypatch.setattr(sidecall, "runner_for", lambda *a, **kw: runner)
    enabled = dict(env, TE_KNOWLEDGE="on", TE_MICROSKILLS="off", TE_LOOPGUARD="off",
                   TE_TOOLPRUNE="off")
    for i in range(2):
        tp = tmp_path / f"one{i}.jsonl"
        tp.write_text("\n".join(map(json.dumps, [
            claude_prompt("read source.txt"),
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "r", "name": "Read",
                 "input": {"file_path": str(source)}},
                {"type": "tool_use", "id": "sh", "name": "Bash",
                 "input": {"command": "pytest"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "r",
                 "content": "     1→observed"}]},
             "toolUseResult": {"type": "text", "file": {
                 "filePath": str(source), "content": "observed\n", "startLine": 1,
                 "numLines": 1, "totalLines": 1}}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}},
        ])))
        run_session(enabled, repo, f"s{i}", str(tp))
    assert len(prompts) == 1
    assert "one or more {ref, symbol?}" in prompts[0]
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    stage = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
    (fact,) = stage.facts.values()
    assert (fact.claim, fact.state) == ("Source is observed", "ACTIVE")
    assert [proof["path"] for proof in fact.spec["proof"]] == ["source.txt"]
    assert "Source is observed" in json.dumps(call(enabled, {
        "hook_event_name": "PostToolUse", "session_id": "inject", "cwd": repo,
        "tool_name": "Read", "tool_input": {"file_path": "source.txt"},
        "tool_response": {"content": "observed"}}))


def _learn_source_knowledge(tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin import sidecall
    source = Path(repo) / "source.txt"
    source.write_text("observed\n")
    other = Path(repo) / "support.txt"
    other.write_text("support\n")
    candidate = {"id": "k", "claim": "Source is observed",
                 "sources": [{"ref": "s1/0.0"}, {"ref": "s1/0.1"}],
                 "detector": {"scope": "pytest", "confirm": "passed"}}
    monkeypatch.setattr(sidecall, "runner_for", lambda *a, **kw: lambda *a: (json.dumps({"facts": [candidate]}), 0))
    enabled = dict(env, TE_KNOWLEDGE="on", TE_MICROSKILLS="off", TE_LOOPGUARD="off", TE_TOOLPRUNE="off")
    for i in range(5):
        tp = tmp_path / f"hook{i}.jsonl"
        events = [
            claude_prompt("read both files"),
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": str(source)}}, {"type": "tool_use", "id": "r2", "name": "Read", "input": {"file_path": str(other)}}, {"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r", "content": "     1→observed"}]}, "toolUseResult": {"type": "text", "file": {"filePath": str(source), "content": "observed\n", "startLine": 1, "numLines": 1, "totalLines": 1}}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r2", "content": "     1→support"}]}, "toolUseResult": {"type": "text", "file": {"filePath": str(other), "content": "support\n", "startLine": 1, "numLines": 1, "totalLines": 1}}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}},
        ]
        tp.write_text("\n".join(map(json.dumps, events)))
        run_session(enabled, repo, f"s{i}", str(tp))
    return enabled


def test_a_knowledge_is_injected_once_per_session(tmp_path, env, repo, monkeypatch):
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    sid = "once"

    def start(source, host=None):
        call(enabled, {"hook_event_name": "SessionStart", "source": source, "session_id": sid, "cwd": repo}, host)

    def read(host=None):
        return "Source is observed" in json.dumps(call(enabled, {
            "hook_event_name": "PostToolUse", "session_id": sid, "cwd": repo,
            "tool_name": "Read", "tool_input": {"file_path": "source.txt"}, "tool_response": {"content": "observed"}}, host))
    start("startup")
    assert read()
    assert not read()
    assert not read()
    start("resume")                       # Claude replays its context: nothing again
    assert not read()
    start("clear")
    assert read()
    assert not read()
    start("compact")
    assert read()
    # Another session is not affected by this one's memory.
    sid = "other-session"
    start("startup")
    assert read()


def test_a_resumed_session_keeps_the_knowledge_it_was_given(tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin.hosts import ClaudeCode
    # Copilot rebuilds a resumed conversation without its start context, but the Knowledge came
    # as tool context, which stays in the history: it is not given again.
    monkeypatch.setattr(ClaudeCode, "keeps_start_context", False)
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)

    def send(event, **kw):
        return json.dumps(call(enabled, dict({"hook_event_name": event, "session_id": "c1", "cwd": repo}, **kw)))
    def read():
        return send("PostToolUse", tool_name="Read", tool_input={"file_path": "source.txt"},
                    tool_response={"content": "observed"})
    send("SessionStart", source="new")
    assert "Source is observed" in read()
    send("SessionStart", source="resume")
    assert "Source is observed" not in read()
    send("SessionStart", source="clear")
    assert "Source is observed" in read()


def test_hook_uses_current_proof_even_when_session_cache_is_warm(tmp_path, env, repo, monkeypatch):
    import threading
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    payload = {"hook_event_name": "PostToolUse", "session_id": "warm", "cwd": repo,
               "tool_name": "Read", "tool_input": {"file_path": "source.txt"},
               "tool_response": {"content": "observed"}}
    assert "Source is observed" in json.dumps(call(enabled, payload))
    (Path(repo) / "support.txt").write_text("changed\n")
    assert "Source is observed" not in json.dumps(call(enabled, dict(payload, session_id="fresh")))
    (Path(repo) / "support.txt").write_text("support\n")
    assert "Source is observed" in json.dumps(call(enabled, dict(payload, session_id="restored")))
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    result = []
    started = threading.Event()
    def invoke():
        started.set()
        result.append(call(enabled, dict(payload, session_id="race")))
    with ctx.store.locked("mechanisms") as acquired:
        assert acquired
        worker = threading.Thread(target=invoke)
        worker.start()
        assert started.wait(2)
        worker.join(0.2)
        assert worker.is_alive()
        stage = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
        stage.facts.clear()
        stage.save(ctx.mech_dir)
    worker.join(5)
    assert not worker.is_alive()
    assert "Source is observed" not in json.dumps(result)


def test_a_revision_replaces_the_stored_contract_at_once(tmp_path, monkeypatch):
    """A revision needs a changed contract or content, not a second confirmation: the stored
    spec and the card change in the same cycle, and the new proofs are checked at delivery."""
    from tokeneconomizer.microskills import distiller
    monkeypatch.setattr(distiller, "PROPOSE_EVERY", 3)
    (tmp_path / "source.txt").write_text("observed\n")
    (tmp_path / "support.txt").write_text("support\n")
    names = ("source.txt", "support.txt")

    def candidate(claim="Source contains observed", session="s0", fid="suggestion"):
        return {"id": fid, "claim": claim,
                "sources": [{"ref": f"{session}/0.{n}"} for n in range(len(names))],
                "detector": {"scope": "pytest", "confirm": "passed"}}

    stage = Knowledge("repo")
    stage.workspace = tmp_path
    stage.runner = lambda *args: (json.dumps({"facts": [candidate()]}), 0)
    for i in range(3):
        fold_session(stage, tmp_path, i, names)
    assert "Source contains observed" in stage.render()
    fid = next(k for k in stage.debug_row() if not k.startswith("_"))
    # The same contract again is no revision.
    for i in range(3, 6):
        fold_session(stage, tmp_path, i, names)
    assert stage.debug_row()[fid]["rev"] == 1
    assert "Source contains observed" in stage.render()
    # A changed claim is one, and it is available at once.
    stage.runner = lambda *args: (
        json.dumps({"facts": [candidate("Revised observation", "s6", fid)]}), 0)
    for i in range(6, 9):
        fold_session(stage, tmp_path, i, names)
    assert stage.debug_row()[fid]["rev"] == 2
    assert "Revised observation" in stage.render()
    # The new contract is verified again before every delivery.
    (tmp_path / "source.txt").write_text("changed\n")
    assert "Revised observation" not in stage.render()
    (tmp_path / "source.txt").write_text("observed\n")
    assert "Revised observation" in stage.render()


def test_a_detector_revision_bumps_the_revision_and_stays_injectable(tmp_path, monkeypatch):
    from tokeneconomizer.microskills import distiller
    monkeypatch.setattr(distiller, "PROPOSE_EVERY", 3)
    (tmp_path / "source.txt").write_text("observed\n")
    names = ("source.txt",)

    def candidate(fid="suggestion", **detector):
        return {"id": fid, "claim": "Source contains observed",
                "sources": [{"ref": "s0/0.0"}],
                "detector": dict({"scope": "pytest", "confirm": "passed"}, **detector)}

    stage = Knowledge("repo", runner=lambda *args: (json.dumps({"facts": [candidate()]}), 0))
    stage.workspace = tmp_path
    for i in range(3):
        fold_session(stage, tmp_path, i, names)
    assert "Source contains observed" in stage.render()
    fid = next(k for k in stage.debug_row() if not k.startswith("_"))
    # Changing only the contradiction detector is still a Knowledge revision, and it retires
    # the fact once a folded session contradicts it.
    stage.runner = lambda *args: (json.dumps({"facts": [candidate(fid, contradict="failed")]}), 0)
    for i in range(3, 6):
        fold_session(stage, tmp_path, i, names)
    assert stage.debug_row()[fid]["rev"] == 2
    assert "Source contains observed" in stage.render()
    for i in range(6, 8):
        fold_session(stage, tmp_path, i, names, output="failed")
    assert stage.debug_row()[fid]["state"] == "RETIRED"
    assert "Source contains observed" not in stage.render()


@pytest.mark.parametrize("parser_available", [True, False])
def test_symbol_requested_in_session_survives_unrelated_edits_and_fails_closed(tmp_path, monkeypatch, parser_available):
    from tokeneconomizer.microskills import distiller
    monkeypatch.setattr(distiller, "PROPOSE_EVERY", 3)
    if not parser_available:
        import tree_sitter_language_pack
        def unavailable(*args):
            raise LookupError("unavailable")
        monkeypatch.setattr(tree_sitter_language_pack, "get_parser", unavailable)
    source = tmp_path / "source.py"
    content = "def target():\n    return 1\n\ndef other():\n    return 2\n"
    source.write_text(content)
    support = tmp_path / "support.txt"
    support.write_text("support\n")
    candidate = {"id": "s", "claim": "Target returns one",
                 "sources": [{"ref": "s0/0.0", "symbol": "target"}, {"ref": "s0/0.1"}],
                 "detector": {"scope": "pytest", "confirm": "passed"}}
    stage = Knowledge("repo", runner=lambda *args: (json.dumps({"facts": [candidate]}), 0))
    stage.workspace = tmp_path
    for i in range(5):
        fold_session(stage, tmp_path, i, ("source.py", "support.txt"))
    assert "Target returns one" in stage.render()
    fact = next(iter(stage.facts.values()))
    evidence = fact.spec["proof"][0]
    assert evidence["kind"] == ("symbol" if parser_available else "file")
    # The requested symbol is the signal when it resolves, the file when it cannot.
    assert stage.signals(fact) == (["target", "support.txt"] if parser_available
                                   else ["source.py", "support.txt"])
    if not parser_available:
        assert evidence["fallback"] == {"symbol": "target", "reason": "symbol-unresolvable"}
    source.write_text(content.replace("return 2", "return 3"))
    assert ("Target returns one" in stage.render()) == parser_available
    source.write_text(content.replace("return 1", "return 4"))
    assert not stage.render()


def test_a_knowledge_about_several_files_holds_while_all_of_them_do(tmp_path, monkeypatch):
    from tokeneconomizer.microskills import distiller
    monkeypatch.setattr(distiller, "PROPOSE_EVERY", 3)
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text(f"{name} observed\n")
    candidates = [{"id": "both", "claim": "a and b agree",
                   "sources": [{"ref": "s0/0.0"}, {"ref": "s1/0.0"}],
                   "detector": {"scope": "pytest", "confirm": "passed"}}]
    stage = Knowledge("repo", runner=lambda *args: (json.dumps({"facts": candidates}), 0))
    stage.workspace = tmp_path
    # The two sources are observed in different sessions, then together in the later ones.
    for i in range(5):
        fold_session(stage, tmp_path, i,
                     ("a.txt",) if i == 0 else ("b.txt",) if i == 1 else ("a.txt", "b.txt"))
    assert "a and b agree" in stage.render()
    assert stage.selection(read="a.txt", max_tokens=5) == ("", [])
    stage.save(tmp_path)
    stage = Knowledge.load("repo", tmp_path)
    stage.workspace = tmp_path
    fact = next(iter(stage.facts.values()))
    assert set(stage.signals(fact)) == {"a.txt", "b.txt"}
    # The engine keeps what each reference resolved to, never the proposal's own entries.
    assert fact.spec["provenance"]["sources"] == [{"path": "a.txt", "session": "s0"},
                                                  {"path": "b.txt", "session": "s1"}]
    assert [proof["path"] for proof in fact.spec["proof"]] == ["a.txt", "b.txt"]
    assert "a and b agree" in stage.render("look at b.txt")
    assert [f.id for f, _ in stage.covering("a.txt")] == [fact.id] == [f.id for f, _ in stage.covering("b.txt")]
    (tmp_path / "b.txt").write_text("changed\n")
    assert "a and b agree" not in stage.render()


def test_a_knowledge_that_synthesizes_other_knowledge_is_refused(tmp_path, monkeypatch):
    from tokeneconomizer.microskills import distiller
    monkeypatch.setattr(distiller, "PROPOSE_EVERY", 3)
    (tmp_path / "source.txt").write_text("observed\n")
    stage = Knowledge("repo", runner=lambda *args: (json.dumps({"facts": [
        {"id": "synthesis", "claim": "combined", "dependencies": ["x", "y"],
         "cite": ["s0", "s1"], "detector": {"scope": "pytest", "confirm": "passed"}}]}), 0))
    stage.workspace = tmp_path
    assert stage._admit({"id": "synthesis", "claim": "combined", "dependencies": ["x", "y"]}) == (False, "invalid-source-or-content")


def test_a_reference_must_resolve_to_one_retained_observation(tmp_path):
    """The engine resolves each ref against the digest and keeps its own proof, never the
    proposal's entries: a ref the digest does not retain is refused, an unobserved file named in
    the claim is refused, and a duplicated ref is refused; two refs resolving to the same file
    are one source, not two."""
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n")
    (tmp_path / "link.py").hardlink_to(tmp_path / "a.py")
    stage = observed_stage(tmp_path, names=("a.py", "link.py"), sessions=2)
    base = {"id": "k", "claim": "alpha returns one"}
    # No session is s9, and no sequence s0 has a second unit: both refs are out of the digest.
    assert stage._admit(dict(base, sources=[{"ref": "s9/0.0"}])) == (False, "out-of-digest")
    assert stage._admit(dict(base, sources=[{"ref": "s0/0.7"}])) == (False, "out-of-digest")
    assert stage._admit(dict(base, sources=[{"ref": "s0/0.0"}])) == (True, "admitted")
    # Two refs that resolve to the same file are one source, not two -- and one is enough.
    assert stage._admit(dict(base, id="k2", claim="alpha is one",
                             sources=[{"ref": "s1/0.0"}, {"ref": "s1/0.1"}])) == (
        True, "admitted")
    (tmp_path / "uncovered.py").write_text("pass\n")
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "uncovered.py").write_text("pass\n")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "test.yml").write_text("name: test\n")
    (tmp_path / "dir" / "my.file.ts").write_text("export {}\n")
    for mention in ("uncovered.py", "./uncovered.py", "It calls uncovered.py.",
                    r"dir\uncovered.py", ".github/workflows/test.yml", "dir/my.file.ts"):
        assert stage._admit(dict(base, id="k3", claim="a.py calls " + mention,
                                 sources=[{"ref": "s0/0.0"}])) == (False, "uncovered-file")
    # The legacy path forms have no reader: a proposal cites the digest's refs.
    assert stage._admit({"id": "legacy", "claim": "alpha returns one", "source": "a.py",
                         "symbol": "alpha"}) == (False, "invalid-source-or-content")
    assert stage._admit(dict(base, id="k4", sources=[{"source": "a.py"}])) == (
        False, "invalid-source-or-content")
    assert stage._admit(dict(base, id="k4", sources=[])) == (False, "invalid-source-or-content")
    assert stage._admit(dict(base, id="k5", sources=[{"ref": "s0/0.0"},
                                                     {"ref": "s0/0.0"}])) == (
        False, "invalid-source-or-content")


def test_two_observed_symbols_in_distinct_files_are_admitted(tmp_path):
    pytest.importorskip("tree_sitter_language_pack")
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    paths = [tmp_path / "a.py", tmp_path / "b.py"]
    for path, symbol in zip(paths, ("alpha", "beta")):
        path.write_text(f"def {symbol}():\n    return 1\n")
    for i in range(2):
        uses, results = [], []
        for n, path in enumerate(paths):
            content = path.read_text()
            uses.append({"type": "tool_use", "id": f"r{n}", "name": "Read", "input": {"file_path": str(path)}})
            results.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"r{n}", "content": content}]},
                            "toolUseResult": {"type": "text", "file": {"filePath": str(path), "content": content, "startLine": 1, "numLines": 2, "totalLines": 2}}})
        uses.append({"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}})
        events = [claude_prompt("read both modules"),
                  {"type": "assistant", "message": {"content": uses}}, *results,
                  {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}}]
        transcript = tmp_path / f"symbols{i}.jsonl"
        transcript.write_text("\n".join(map(json.dumps, events)))
        stage.update(transcript, iid=f"s{i}")
    candidate = {"id": "k", "claim": "both return one",
                 "detector": {"scope": "pytest", "confirm": "passed"},
                 "sources": [{"ref": "s1/0.0", "symbol": "alpha"},
                             {"ref": "s1/0.1", "symbol": "beta"}]}
    assert stage._admit(candidate) == (True, "admitted")
    fact = next(iter(stage.facts.values()))
    assert [(p["path"], p["symbol"]) for p in fact.spec["proof"]] == [("a.py", "alpha"), ("b.py", "beta")]
    assert set(stage.signals(fact)) == {"alpha", "beta"}
    assert [source["symbol"] for source in fact.spec["provenance"]["sources"]] == [
        "alpha", "beta"]
    assert "both return one" in stage.render()
    fact.injection = "é" * 100
    assert stage.selection(read="a.py", max_tokens=100)[0]


def test_paid_native_and_knowledge_share_one_proposal_budget(tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin import sidecall
    calls = []
    source = __import__("pathlib").Path(repo) / "source.txt"
    source.write_text("observed\n")
    support = Path(repo) / "support.txt"
    support.write_text("support\n")
    detector = {"scope": "pytest", "confirm": "passed"}
    facts = [{"id": "native", "claim": "native claim", "cite": ["s0", "s1"], "detector": detector}]
    facts += [{"id": f"k{i}", "claim": f"knowledge {i}",
               "sources": [{"ref": "s1/0.0" if i != 1 else "invalid\0ref"}],
               "detector": detector}
              for i in range(8)]
    def runner(prompt, model):
        calls.append(prompt)
        return json.dumps({"facts": facts}), 5
    monkeypatch.setattr(sidecall, "runner_for", lambda *a, **kw: runner)
    enabled = dict(env, TE_KNOWLEDGE="on", TE_MICROSKILLS="distiller",
                   TE_LOOPGUARD="off", TE_TOOLPRUNE="off")
    for i in range(3):
        path = tmp_path / f"shared{i}.jsonl"
        events = [
            claude_prompt("read both files"),
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": str(source)}}, {"type": "tool_use", "id": "other", "name": "Read", "input": {"file_path": str(support)}}, {"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r", "content": "observed\n"}]}, "toolUseResult": {"type": "text", "file": {"filePath": str(source), "content": "observed\n", "startLine": 1, "numLines": 1, "totalLines": 1}}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "other", "content": "support\n"}]}, "toolUseResult": {"type": "text", "file": {"filePath": str(support), "content": "support\n", "startLine": 1, "numLines": 1, "totalLines": 1}}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}},
        ]
        path.write_text("\n".join(map(json.dumps, events)))
        run_session(enabled, repo, f"s{i}", str(path))
    assert len(calls) == 1
    assert "to be cited by ref" in calls[0] and "observed_sources" not in calls[0]
    assert "up to 8 candidates TOTAL" in calls[0] and "<=4" not in calls[0]
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    from tokeneconomizer.microskills.distiller import Distiller
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    native = Distiller.load(ctx.repo.label, ctx.mech_dir)
    knowledge = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
    assert len(native.facts) == 1
    assert {fact.claim for fact in knowledge.facts.values()} == {
        f"knowledge {i}" for i in (0, 2, 3, 4, 5, 6)}
    batches = [row["injection"]["shared_proposals"] for row in ctx.store.read_lines("ledger.jsonl")
               if "shared_proposals" in (row.get("injection") or {})]
    assert batches == [{
        "native": {"proposed": 1, "admitted": 1},
        "knowledge": {"proposed": 7, "admitted": 6},
    }]


def test_one_observed_source_still_shares_the_proposal_call(tmp_path, env, repo, monkeypatch):
    """The shared call is not gated on two distinct files: one observed read is enough to put the
    Knowledge context in front of the same proposer as the native facts, once."""
    from tokeneconomizer.plugin import sidecall
    calls = []
    source = Path(repo) / "source.txt"
    source.write_text("observed\n")

    def runner(prompt, model):
        calls.append(prompt)
        return json.dumps({"facts": []}), 0

    monkeypatch.setattr(sidecall, "runner_for", lambda *a, **kw: runner)
    enabled = dict(env, TE_KNOWLEDGE="on", TE_MICROSKILLS="distiller",
                   TE_LOOPGUARD="off", TE_TOOLPRUNE="off")
    tp = tmp_path / "one-source.jsonl"
    tp.write_text("\n".join(map(json.dumps, [
        claude_prompt("read source.txt"),
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "r", "name": "Read",
             "input": {"file_path": str(source)}},
            {"type": "tool_use", "id": "sh", "name": "Bash",
             "input": {"command": "pytest"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "r", "content": "observed\n"}]},
         "toolUseResult": {"type": "text", "file": {
             "filePath": str(source), "content": "observed\n", "startLine": 1,
             "numLines": 1, "totalLines": 1}}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}},
    ])))
    for i in range(2):
        run_session(enabled, repo, f"s{i}", str(tp))
    assert len(calls) == 1
    assert "Knowledge context:" in calls[0]
    assert '"s0/0.0"' in calls[0] and "observed_sources" not in calls[0]


@pytest.mark.parametrize("failure", ["empty_window", "capture_error", "admission_error"])
def test_native_proposal_survives_unavailable_knowledge_context(tmp_path, env, repo, monkeypatch, failure):
    from tokeneconomizer.plugin import sidecall
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    from tokeneconomizer.microskills.distiller import Distiller

    calls = []
    candidate = {"id": "native", "claim": "native claim", "cite": ["s0", "s1"],
                 "detector": {"scope": "pytest", "confirm": "passed"}}
    def runner(prompt, model):
        calls.append(prompt)
        return json.dumps({"facts": [candidate]}), 5
    monkeypatch.setattr(sidecall, "runner_for", lambda *a, **kw: runner)
    if failure == "empty_window":
        monkeypatch.setattr(Knowledge, "update", lambda *a, **kw: None)
    else:
        monkeypatch.setattr(Knowledge, "has_proposal_sources", lambda self: True)
        def fail(*args):
            raise ValueError("invalid Knowledge context")
        method = "_proposal_prompt" if failure == "capture_error" else "_apply_proposals"
        monkeypatch.setattr(Knowledge, method, fail)
    enabled = dict(env, TE_KNOWLEDGE="on", TE_MICROSKILLS="distiller",
                   TE_LOOPGUARD="off", TE_TOOLPRUNE="off")
    for i in range(3):
        path = tmp_path / f"native{i}.jsonl"
        events = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}},
        ]
        path.write_text("\n".join(map(json.dumps, events)))
        run_session(enabled, repo, f"s{i}", str(path))
    assert len(calls) == 1
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    native = Distiller.load(ctx.repo.label, ctx.mech_dir)
    assert "native" in native.facts


# ---- Knowledge from a Pi read of part of a file -------------------------------------------
def claude_trace(path, command="pytest", output="passed"):
    """The digest's view of a session: one finished check (observations read the Pi log)."""
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": command}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "sh", "content": output}]}},
    ]
    path.write_text("\n".join(map(json.dumps, events)))


def partial_stage(tmp_path, sessions=2):
    """A `Knowledge` fed Pi sessions that each read line 2 of `source.py` and passed pytest."""
    source = tmp_path / "source.py"
    source.write_bytes(SOURCE)
    (tmp_path / "support.txt").write_text("support\n")
    args = {"path": "source.py", "offset": 2, "limit": 1}
    text = pi_read(SOURCE, 2, 1)
    captures = capture_read(tmp_path, args, text)
    stage = Knowledge("repo")
    stage.workspace, stage.host = tmp_path, "pi"
    for i in range(sessions):
        pi, trace = tmp_path / f"pi{i}.jsonl", tmp_path / f"trace{i}.jsonl"
        reads_session(pi, tmp_path, [("r", args, text, False),
                                     ("support", {"path": "support.txt"}, "support\n", False)])
        claude_trace(trace)
        stage.update(trace, iid=f"s{i}", observed_transcript=pi, captures=captures)
    return stage, source


def partial_candidate(**fields):
    """A proposal about one partial read: the ref of the first read of session s0's sequence,
    with the symbol its lines crossed."""
    symbol = fields.pop("symbol", "alpha")
    source = {"ref": "s0/0.0"}
    if symbol is not None:
        source["symbol"] = symbol
    candidate = {"id": "alpha-one", "claim": "Alpha returns one", "sources": [source],
                 "detector": {"scope": "pytest", "confirm": "passed"}}
    candidate.update(fields)
    return {k: v for k, v in candidate.items() if v is not None}


def test_partial_knowledge_admits_on_the_symbol_its_read_crossed(tmp_path):
    stage, _ = partial_stage(tmp_path)
    assert stage._admit(partial_candidate()) == (True, "admitted")
    spec = next(iter(stage.facts.values())).spec
    assert spec["proof"][0]["kind"] == "symbol" and spec["proof"][0]["symbol"] == "alpha"
    assert spec["provenance"]["observed"]["source.py"] == {"reads": [{"offset": 2, "lines": 1}], "total_lines": 7}


def test_partial_knowledge_refuses_anything_but_an_observed_symbol(tmp_path):
    stage, source = partial_stage(tmp_path)
    # no symbol at all: an excerpt cannot support a file-wide claim
    assert stage._admit(partial_candidate(symbol=None)) == (False, "partial-needs-symbol")
    # declared in the file, but not in the lines the read returned
    assert stage._admit(partial_candidate(symbol="beta")) == (False, "symbol-not-observed")
    assert stage._admit(partial_candidate(symbol="gamma")) == (False, "symbol-not-observed")
    assert not stage.facts
    # the symbol changed after the read: no partial proof survives it, and no file fallback
    source.write_bytes(SOURCE.replace(b"return 1", b"return 9"))
    assert stage._admit(partial_candidate()) == (False, "stale-proof")
    assert not stage.facts


def test_partial_proof_follows_the_whole_symbol_before_and_after_injection(tmp_path):
    stage, source = partial_stage(tmp_path, sessions=5)
    assert stage._admit(partial_candidate()) == (True, "admitted")
    assert "Alpha returns one" in stage.render()
    # a line of the symbol the read never returned is part of its proof
    source.write_bytes(SOURCE.replace(b"    return 1", b"    return 9"))
    assert "Alpha returns one" not in stage.render()
    source.write_bytes(SOURCE)
    assert "Alpha returns one" in stage.render()
    # a comment inside the symbol changes nothing it attests
    source.write_bytes(SOURCE.replace(b"    return 1", b"    # the one\n    return 1"))
    assert "Alpha returns one" in stage.render()
    # neither does another symbol
    source.write_bytes(SOURCE.replace(b"return 2", b"return 3"))
    assert "Alpha returns one" in stage.render()


def test_a_partial_observation_never_stores_the_captured_file(tmp_path):
    stage, _ = partial_stage(tmp_path)
    assert stage._admit(partial_candidate()) == (True, "admitted")
    stage.save(tmp_path)
    state = json.loads((tmp_path / "knowledge_state" / "repo.json").read_text())
    stored = json.dumps(state)
    assert "beta marker" not in stored and SOURCE.decode() not in stored
    (unit,) = [unit for unit in state["digest"]["sequences"][0]["units"]
               if unit["path"] == "source.py"]
    # Only what the read returned is kept, and that text is what the proposer is shown.
    assert unit["content"] == "    return 1"
    assert unit["observed"]["total_lines"] == 7
    assert "proof" not in unit and "excerpt" not in unit
    shown = stage.digest.view()["excerpts"][0]
    assert shown["text"] == "    return 1" and shown["observed_lines"] == "2-2 of 7"


def test_the_proposer_is_told_what_a_partial_source_can_support(tmp_path):
    stage, _ = partial_stage(tmp_path)
    prompts = []
    stage.runner = lambda prompt, model: (prompts.append(prompt) or '{"facts": []}', 0)
    stage._maybe_propose()
    # An empty proposal is valid: it admits nothing and still uses the tick.
    assert (stage.last_propose, stage.facts) == (stage.now, {})
    assert "read only in part" in prompts[0]
    assert "observed_lines" in prompts[0]
    assert "coherent, reusable mechanism" in prompts[0]
    # One observed source is enough; the proposal names the references and nothing else.
    assert "one or more {ref, symbol?}" in prompts[0]
    assert "is enough" in prompts[0]
    assert "at least two distinct files" not in prompts[0]
    assert "Do not add flow, role or cite to a Knowledge" in prompts[0]


def symbol_less_partial_stage(tmp_path, sessions=2):
    """A `Knowledge` fed Pi sessions that each read line 3 of `source.py`: a blank line."""
    source = tmp_path / "source.py"
    source.write_bytes(SOURCE)
    (tmp_path / "support.txt").write_text("support\n")
    args = {"path": "source.py", "offset": 3, "limit": 1}
    text = pi_read(SOURCE, 3, 1)
    captures = capture_read(tmp_path, args, text)
    stage = Knowledge("repo")
    stage.workspace, stage.host = tmp_path, "pi"
    for i in range(sessions):
        pi, trace = tmp_path / f"blank{i}.jsonl", tmp_path / f"blanktrace{i}.jsonl"
        reads_session(pi, tmp_path, [("r", args, text, False),
                                     ("support", {"path": "support.txt"}, "support\n", False)])
        claude_trace(trace)
        stage.update(trace, iid=f"s{i}", observed_transcript=pi, captures=captures)
    return stage, source


def test_a_partial_source_no_symbol_proves_is_not_offered_to_the_proposer(tmp_path):
    stage, _ = symbol_less_partial_stage(tmp_path)
    view = stage.digest.view()
    # the read crossed no declaration: it stays out of the refs and excerpts the proposer sees
    assert {excerpt["path"] for excerpt in view["excerpts"]} == {"support.txt"}
    assert [sequence["refs"] for sequence in view["sequences"]] == [["s0/0.1"], ["s1/0.1"]]
    # the observation is kept, so a proposal that cites it is refused for that and nothing else
    assert stage.digest.sequences[0]["units"][0]["path"] == "source.py"
    assert stage._admit(partial_candidate(symbol="alpha")) == (False, "out-of-digest")
    assert not stage.facts


def test_the_cli_shows_the_scope_a_partial_knowledge_really_read(tmp_path, env, repo,
                                                                 monkeypatch, capsys):
    """Story 4: what a partial read actually returned stays inspectable, not just its source."""
    from pathlib import Path
    from tokeneconomizer.plugin import cli
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    root = Path(repo)
    (root / "source.py").write_bytes(SOURCE)
    (root / "support.txt").write_text("support\n")
    args = {"path": "source.py", "offset": 2, "limit": 1}
    text = pi_read(SOURCE, 2, 1)
    captures = capture_read(root, args, text)
    ctx = LiveContext.build(ClaudeCode(), repo, env)
    stage = Knowledge(workspace_id(ctx.repo.label, ctx.repo.root))
    stage.workspace, stage.host = root, "pi"
    for i in range(2):
        pi, trace = tmp_path / f"cli{i}.jsonl", tmp_path / f"clitrace{i}.jsonl"
        reads_session(pi, root, [("r", args, text, False), ("support", {"path": "support.txt"}, "support\n", False)])
        claude_trace(trace)
        stage.update(trace, iid=f"s{i}", observed_transcript=pi, captures=captures)
    assert stage._admit(partial_candidate()) == (True, "admitted")
    stage.save(ctx.mech_dir)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert cli.main(["--host", "claude", "--cwd", repo, "microskills"]) == 0
    out = capsys.readouterr().out
    assert "sources=source.py" in out
    assert "ACTIVE" in out and "rev=1" in out and "proof=valid" in out
    assert "evidence=source.py session=s0 symbol=alpha" in out
    assert '"source.py": {"reads": [{"lines": 1, "offset": 2}], "total_lines": 7}' in out


def test_a_failed_fold_keeps_the_captures_for_a_retry(tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.knowledge import capture
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.fold import _fold_knowledge
    from tokeneconomizer.plugin.hosts import ClaudeCode
    from types import SimpleNamespace
    adapter = SimpleNamespace(env_vocabulary=lambda: {})
    ctx = LiveContext.build(ClaudeCode(), repo, dict(env, TE_KNOWLEDGE="on"))
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("{}")
    directory = Path(capture.session_dir(ctx.store, "s1"))
    directory.mkdir(parents=True)
    (directory / "index.json").write_text("{}")

    def boom(*args, **kwargs):
        raise RuntimeError("fold failed")
    monkeypatch.setattr(Knowledge, "update", boom)
    with pytest.raises(RuntimeError):
        _fold_knowledge(ctx, adapter, str(transcript), "s1")
    assert directory.exists()

    monkeypatch.setattr(Knowledge, "update", lambda *a, **kw: None)
    _fold_knowledge(ctx, adapter, str(transcript), "s1")
    assert not directory.exists()


def learn_knowledge(tmp_path, env, repo, monkeypatch, files, candidates, also=()):
    """Learn Knowledge through five live sessions whose request reads every file and passes a
    test run. Each candidate names one `source`; `also` names further files read to add to it.
    Every one of them cites the ref of the unit the first session's sequence retained."""
    from tokeneconomizer.plugin import sidecall
    files = dict(files, **{"support.txt": "support\n"})
    paths = {}
    for name, content in files.items():
        paths[name] = Path(repo) / name
        paths[name].parent.mkdir(parents=True, exist_ok=True)
        paths[name].write_text(content)
    facts = []
    order = list(paths)
    for candidate in candidates:
        fact = dict(candidate)
        source = {"ref": f"s0/0.{order.index(fact.pop('source'))}"}
        if "symbol" in fact:
            source["symbol"] = fact.pop("symbol")
        fact.update(sources=[source] + [{"ref": f"s0/0.{order.index(name)}"} for name in also],
                    detector={"scope": "pytest", "confirm": "passed"})
        facts.append(fact)
    monkeypatch.setattr(sidecall, "runner_for", lambda *a, **kw: lambda *a: (json.dumps({"facts": facts}), 0))
    enabled = dict(env, TE_KNOWLEDGE="on", TE_MICROSKILLS="off", TE_LOOPGUARD="off", TE_TOOLPRUNE="off")
    for i in range(5):
        uses, results = [], []
        for n, (name, path) in enumerate(paths.items()):
            content = files[name]
            lines = len(content.splitlines())
            uses.append({"type": "tool_use", "id": f"r{n}", "name": "Read", "input": {"file_path": str(path)}})
            results.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"r{n}", "content": content}]}, "toolUseResult": {"type": "text", "file": {"filePath": str(path), "content": content, "startLine": 1, "numLines": lines, "totalLines": lines}}})
        uses.append({"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}})
        events = [claude_prompt("read every file and run the tests"),
                  {"type": "assistant", "message": {"content": uses}}, *results,
                  {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}}]
        tp = tmp_path / f"rank{i}.jsonl"
        tp.write_text("\n".join(map(json.dumps, events)))
        run_session(enabled, repo, f"s{i}", str(tp))
    return enabled


def prompt(enabled, repo, sid, text, **limits):
    env = dict(enabled, **limits)
    return json.dumps(call(env, {"hook_event_name": "UserPromptSubmit", "session_id": sid, "cwd": repo, "prompt": text}))


def test_read_budget_prioritizes_the_highest_firing_card(tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    enabled = learn_knowledge(tmp_path, env, repo, monkeypatch,
                              {"a.txt": "observed\n", "b.txt": "observed\n"},
                              [{"id": "a", "claim": "first card", "source": "a.txt"},
                               {"id": "b", "claim": "second card", "source": "b.txt"}],
                              also=("support.txt",))
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    stage = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
    by_source = {f.spec["proof"][0]["path"]: f for f in stage.facts.values()}
    by_source["a.txt"].life.fire_num, by_source["a.txt"].life.fire_den = 5, 10
    by_source["b.txt"].life.fire_num, by_source["b.txt"].life.fire_den = 9, 10
    stage.save(ctx.mech_dir)
    payload = {"hook_event_name": "PostToolUse", "session_id": "read", "cwd": repo,
               "tool_name": "Read", "tool_input": {"file_path": "support.txt"},
               "tool_response": {"content": "support"}}
    text = json.dumps(call(dict(enabled, TE_KNOWLEDGE_MAX_CARDS="1"), payload))
    assert "second card" in text and "first card" not in text


def test_a_small_budget_keeps_the_stronger_match_then_the_higher_firing_rate(
        tmp_path, env, repo, monkeypatch):
    """Story 9: with a budget too small for every match, the strongest match is injected first,
    then the one with the higher firing rate, and registration order only breaks a tie."""
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    body = "observed\n"
    names = ["pkg/deep.txt", "lib/full.txt", "lib/twin.txt", "lib/rare.txt"]
    enabled = learn_knowledge(
        tmp_path, env, repo, monkeypatch, {n: body for n in names},
        [{"id": n.split("/")[1][:4], "claim": f"{n} is observed", "source": n} for n in names])
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    one = dict(TE_KNOWLEDGE_MAX_CARDS="1")
    # Registration order puts the file-name match first; the full path is the stronger match.
    assert "lib/full.txt is observed" in prompt(enabled, repo, "b", "read deep.txt and lib/full.txt", **one)
    assert "lib/full.txt is observed" in prompt(enabled, repo, "c", "lib/full.txt then deep.txt", **one)
    # Equal matches: the higher firing rate first, registration order when rates tie.
    both = "lib/twin.txt and lib/rare.txt"
    assert "lib/twin.txt is observed" in prompt(enabled, repo, "d", both, **one)
    stage = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
    by_source = {f.spec["proof"][0]["path"]: f for f in stage.facts.values()}
    rare, twin = by_source["lib/rare.txt"].life, by_source["lib/twin.txt"].life
    rare.fire_num, rare.fire_den, twin.fire_num, twin.fire_den = 9, 10, 5, 10
    stage.save(ctx.mech_dir)
    assert "lib/rare.txt is observed" in prompt(enabled, repo, "e", both, **one)
    # Delivered native facts do not alter the Knowledge limit.
    ctx.store.write("injection.json", {"rendered": "# native\n- A\n- B\n"})
    together = dict(enabled, TE_MICROSKILLS="envfacts")
    start = {"hook_event_name": "SessionStart", "source": "startup", "session_id": "n", "cwd": repo}
    assert "- B" in json.dumps(call(dict(together, TE_MICROSKILLS_MAX_FACTS="3"), start))
    text = prompt(together, repo, "n", "deep.txt lib/full.txt lib/twin.txt", **one)
    assert text.count("is observed") == 1 and "lib/full.txt is observed" in text


def test_a_symbol_named_in_the_prompt_outranks_a_file_match(tmp_path, env, repo, monkeypatch):
    """A symbol source is a Knowledge Signal on its own: naming it needs no file named."""
    pytest.importorskip("tree_sitter_language_pack")
    code = "def target():\n    return 1\n"
    enabled = learn_knowledge(
        tmp_path, env, repo, monkeypatch, {"first.txt": "observed\n", "second.py": code},
        [{"id": "file", "claim": "first.txt is observed", "source": "first.txt"},
         {"id": "sym", "claim": "target returns one", "source": "second.py", "symbol": "target"}])
    text = prompt(enabled, repo, "a", "in first.txt look at target", TE_KNOWLEDGE_MAX_CARDS="1")
    assert "target returns one" in text and "first.txt is observed" not in text


# ---- the digest: work sequences, their budget, and the refs a proposal cites ---------------
def claude_read(tmp_path, name, n=0):
    """A complete `Read` of a workspace file, as Claude Code logs it."""
    content = (tmp_path / name).read_text()
    lines = len(content.splitlines())
    return [{"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": f"r{n}", "name": "Read",
                 "input": {"file_path": str(tmp_path / name)}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"r{n}", "content": content}]},
             "toolUseResult": {"type": "text", "file": {
                 "filePath": str(tmp_path / name), "content": content, "startLine": 1,
                 "numLines": lines, "totalLines": lines}}}]


def fold_events(stage, tmp_path, iid, events):
    """Fold one session's Claude transcript under `iid`."""
    path = tmp_path / f"{iid}.jsonl"
    path.write_text("\n".join(map(json.dumps, events)))
    stage.update(path, iid=iid)


def digest_view(stage):
    """The digest the proposer is shown for this stage: the sequences and their excerpts."""
    from tests.fixtures import knowledge_digest
    prompts = []
    stage.runner = lambda prompt, model: (prompts.append(prompt) or '{"facts": []}', 0)
    stage._maybe_propose()
    return knowledge_digest(prompts[0])


def test_two_requests_in_one_session_are_two_sequences_with_their_own_reads(tmp_path):
    for name in ("first.txt", "second.txt"):
        (tmp_path / name).write_text(f"{name} observed\n")
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    fold_events(stage, tmp_path, "s0", [
        claude_prompt("read first.txt"), *claude_read(tmp_path, "first.txt"),
        claude_prompt("now read second.txt", "2026-11-24T10:05:00.000Z"),
        *claude_read(tmp_path, "second.txt")])
    view = digest_view(stage)
    assert [(s["id"], s["message"], s["refs"]) for s in view["sequences"]] == [
        ("s0/0", "read first.txt", ["s0/0.0"]),
        ("s0/1", "now read second.txt", ["s0/1.0"])]
    assert [(e["refs"], e["path"]) for e in view["excerpts"]] == [
        (["s0/0.0"], "first.txt"), (["s0/1.0"], "second.txt")]


def test_a_request_that_read_nothing_still_takes_its_slot(tmp_path):
    """A work sequence is a message and the work that follows it; no work is still a sequence."""
    (tmp_path / "first.txt").write_text("observed\n")
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    fold_events(stage, tmp_path, "s0", [
        claude_prompt("read first.txt"), *claude_read(tmp_path, "first.txt"),
        claude_prompt("now just explain it", "2026-11-24T10:05:00.000Z")])
    view = digest_view(stage)
    assert [(s["id"], s["message"], s["refs"]) for s in view["sequences"]] == [
        ("s0/0", "read first.txt", ["s0/0.0"]),
        ("s0/1", "now just explain it", [])]
    assert [e["refs"] for e in view["excerpts"]] == [["s0/0.0"]]


def test_a_session_folded_late_lands_at_its_own_time_position(tmp_path):
    """One fold is one process, so a session can be folded long after a newer one: the window is
    the eight newest requests by message time, never by fold order."""
    for n in range(9):
        (tmp_path / f"f{n}.txt").write_text(f"file {n}\n")
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    for n in (0, 2, 4, 6, 8, 1, 3, 5, 7):
        fold_events(stage, tmp_path, f"s{n}", [
            claude_prompt(f"read f{n}", f"2026-11-24T1{n}:00:00.000Z"),
            *claude_read(tmp_path, f"f{n}.txt")])
    # s0 is a request older than the other eight, folded first and dropped first.
    assert [s["id"] for s in digest_view(stage)["sequences"]] == [
        f"s{n}/0" for n in range(1, 9)]
    assert [e["refs"] for e in digest_view(stage)["excerpts"]] == [
        [f"s{n}/0.0"] for n in range(1, 9)]


def test_a_request_with_no_recorded_time_still_sorts_deterministically(tmp_path):
    for n in range(3):
        (tmp_path / f"f{n}.txt").write_text(f"file {n}\n")
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    fold_events(stage, tmp_path, "s0", [
        claude_prompt("read f0", "2026-11-24T10:00:00.000Z"),
        *claude_read(tmp_path, "f0.txt")])
    for n in (1, 2):
        fold_events(stage, tmp_path, f"s{n}", [
            {"type": "user", "message": {"role": "user",
                                         "content": [{"type": "text", "text": f"read f{n}"}]}},
            *claude_read(tmp_path, f"f{n}.txt")])
    # The dated request comes first; the two undated ones follow, ordered by session.
    assert [s["id"] for s in digest_view(stage)["sequences"]] == ["s0/0", "s1/0", "s2/0"]


def test_a_sequence_stops_at_the_first_unit_that_does_not_fit(tmp_path):
    """The first unit that would push a sequence past its 16 000 characters ends retention: it is
    dropped, and so is a later, smaller one -- nothing is packed out of order."""
    (tmp_path / "big.txt").write_text("".join(f"line {n}\n" for n in range(1000)))
    (tmp_path / "huge.txt").write_text("".join(f"line {n}\n" for n in range(800)))
    (tmp_path / "small.txt").write_text("small\n")
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    fold_events(stage, tmp_path, "s0", [
        claude_prompt("read all three"),
        *claude_read(tmp_path, "big.txt", 0), *claude_read(tmp_path, "huge.txt", 1),
        *claude_read(tmp_path, "small.txt", 2)])
    view = digest_view(stage)
    assert view["sequences"][0]["refs"] == ["s0/0.0"]
    assert [e["path"] for e in view["excerpts"]] == ["big.txt"]
    # The small unit after the overflow cannot be cited either: its ref is not in the digest.
    assert stage._admit({"id": "k", "claim": "small is read", "sources": [{"ref": "s0/0.2"}],
                         "detector": {"scope": "pytest", "confirm": "passed"}}) == (
        False, "out-of-digest")


def test_a_first_unit_too_large_leaves_the_sequence_with_nothing_to_cite(tmp_path):
    (tmp_path / "huge.txt").write_text("".join(f"line {n}\n" for n in range(2000)))
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    fold_events(stage, tmp_path, "s0", [
        claude_prompt("read the huge file"), *claude_read(tmp_path, "huge.txt")])
    view = digest_view(stage)
    assert [(s["id"], s["refs"]) for s in view["sequences"]] == [("s0/0", [])]
    assert view["excerpts"] == []
    assert not stage.has_proposal_sources()
    assert stage._admit({"id": "k", "claim": "huge is read", "sources": [{"ref": "s0/0.0"}],
                         "detector": {"scope": "pytest", "confirm": "passed"}}) == (
        False, "out-of-digest")


def test_each_sequence_keeps_its_own_budget(tmp_path):
    (tmp_path / "big.txt").write_text("".join(f"line {n}\n" for n in range(1000)))
    (tmp_path / "even.txt").write_text("".join(f"line {n}\n" for n in range(900)))
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    fold_events(stage, tmp_path, "s0", [
        claude_prompt("read big.txt"), *claude_read(tmp_path, "big.txt", 0),
        claude_prompt("now read even.txt", "2026-11-24T10:05:00.000Z"),
        *claude_read(tmp_path, "even.txt", 1)])
    # Each fits its own sequence: had they shared one budget, the second would not be there.
    assert [s["refs"] for s in digest_view(stage)["sequences"]] == [["s0/0.0"], ["s0/1.0"]]
    assert stage._admit({"id": "k", "claim": "both files are read",
                         "sources": [{"ref": "s0/0.0"}, {"ref": "s0/1.0"}],
                         "detector": {"scope": "pytest", "confirm": "passed"}}) == (
        True, "admitted")


def test_a_sequences_request_counts_against_its_budget(tmp_path):
    """The bounded message context is part of what a sequence keeps: the same read fits a short
    request and not a long one."""
    (tmp_path / "big.txt").write_text("".join(f"line {n}\n" for n in range(1550)))
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    fold_events(stage, tmp_path, "s0", [
        claude_prompt("read big.txt"), *claude_read(tmp_path, "big.txt", 0)])
    fold_events(stage, tmp_path, "s1", [
        claude_prompt("read big.txt " + "please " * 400),
        *claude_read(tmp_path, "big.txt", 1)])
    view = digest_view(stage)
    assert [len(s["message"]) for s in view["sequences"]] == [12, 2000]   # bounded context
    assert [s["refs"] for s in view["sequences"]] == [["s0/0.0"], []]


def test_a_request_appended_after_a_session_is_folded_stays_out(tmp_path, env, repo, monkeypatch):
    """A session is folded once, so messages a resume appends never re-enter the digest."""
    from tokeneconomizer.plugin import sidecall
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    monkeypatch.setattr(sidecall, "runner_for", lambda *a, **kw: lambda *a: ('{"facts": []}', 0))
    root = Path(repo)
    (root / "logged.txt").write_text("logged\n")
    (root / "later.txt").write_text("later\n")
    enabled = dict(env, TE_KNOWLEDGE="on", TE_MICROSKILLS="off", TE_LOOPGUARD="off",
                   TE_TOOLPRUNE="off")
    transcript = tmp_path / "resumed.jsonl"
    transcript.write_text("\n".join(map(json.dumps, [
        claude_prompt("read logged.txt"), *claude_read(root, "logged.txt")])))
    run_session(enabled, repo, "resumed", str(transcript))
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)

    def stored():
        stage = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
        return [s["id"] for s in stage.digest.sequences], stage.digest.state()
    ids, before = stored()
    with transcript.open("a") as stream:
        stream.write("\n" + "\n".join(map(json.dumps, [
            claude_prompt("now read later.txt", "2026-11-24T11:00:00.000Z"),
            *claude_read(root, "later.txt")])))
    run_session(enabled, repo, "resumed", str(transcript))
    assert stored() == (ids, before) == (["resumed/0"], before)
    assert "later.txt" not in json.dumps(before)


def test_the_digest_comes_back_identical_when_the_state_is_reloaded(tmp_path):
    for n in range(9):
        (tmp_path / f"f{n}.txt").write_text(f"file {n}\n")
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    for n in range(9):
        fold_events(stage, tmp_path, f"s{n}", [
            claude_prompt(f"read f{n}", f"2026-11-24T1{n}:00:00.000Z"),
            *claude_read(tmp_path, f"f{n}.txt")])
    stage.save(tmp_path)
    state = json.loads((tmp_path / "knowledge_state" / "repo.json").read_text())
    again = Knowledge.load("repo", tmp_path)
    again.workspace = tmp_path
    assert again.digest.state() == stage.digest.state() == {"sequences": state["digest"]["sequences"]}
    assert again.digest.view() == stage.digest.view()
    assert [s["id"] for s in again.digest.sequences] == [f"s{n}/0" for n in range(1, 9)]


def test_a_background_notification_opens_no_work_sequence(tmp_path):
    (tmp_path / "first.txt").write_text("observed\n")
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    fold_events(stage, tmp_path, "s0", [
        claude_prompt("read first.txt"), *claude_read(tmp_path, "first.txt"),
        {"type": "user", "origin": {"kind": "task-notification"},
         "message": {"role": "user", "content": [
             {"type": "text", "text": "<task-notification>done</task-notification>"}]}}])
    assert [s["id"] for s in digest_view(stage)["sequences"]] == ["s0/0"]


def test_eleven_reads_stay_in_the_digest_although_the_session_view_keeps_ten(tmp_path):
    """The digest has no per-session path cap: a sequence is bounded by its own budget only."""
    from tokeneconomizer.knowledge.observation import observations
    names = [f"f{n}.txt" for n in range(11)]
    for name in names:
        (tmp_path / name).write_text(f"{name}\n")
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    transcript = tmp_path / "s0.jsonl"
    fold_events(stage, tmp_path, "s0", [
        claude_prompt("read all of them"),
        *[entry for n, name in enumerate(names) for entry in claude_read(tmp_path, name, n)]])
    assert list(observations(transcript, tmp_path)) == names[:10]     # the session view
    assert [e["path"] for e in digest_view(stage)["excerpts"]] == names  # the digest


def test_the_digest_shows_the_code_its_budget_counted(tmp_path):
    """The text shown is the retained code itself, not a shorter prompt excerpt: what the budget
    counted is what the proposer can read and cite."""
    (tmp_path / "long.txt").write_text("".join(f"line {n}\n" for n in range(400)))
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    fold_events(stage, tmp_path, "s0", [
        claude_prompt("read long.txt"), *claude_read(tmp_path, "long.txt")])
    (shown,) = digest_view(stage)["excerpts"]
    content = (tmp_path / "long.txt").read_text()
    assert len(content) > 2000 and shown["text"] == content


# ---- the catalogue: one entry per path and compatible version -------------------------------
def test_a_repeated_complete_read_is_shown_and_counted_once(tmp_path):
    """Two reads of one file return the same code, so the catalogue shows it once, keeps both
    refs in read order, and the sequence's budget charges its characters once."""
    (tmp_path / "big.txt").write_text("".join(f"line {n}\n" for n in range(1500)))
    (tmp_path / "small.txt").write_text("small\n")
    stage = Knowledge("repo")
    stage.workspace = tmp_path
    fold_events(stage, tmp_path, "s0", [
        claude_prompt("read big.txt, small.txt, then big.txt again"),
        *claude_read(tmp_path, "big.txt", 0), *claude_read(tmp_path, "small.txt", 1),
        *claude_read(tmp_path, "big.txt", 2)])
    view = digest_view(stage)
    # Each read keeps the ref of its own rank, and the sequence lists them in read order.
    assert [s["refs"] for s in view["sequences"]] == [["s0/0.0", "s0/0.1", "s0/0.2"]]
    assert [(e["path"], e["refs"]) for e in view["excerpts"]] == [
        ("big.txt", ["s0/0.0", "s0/0.2"]), ("small.txt", ["s0/0.1"])]
    # Charged once, the big file leaves room for the small one; charged twice it would not.
    assert view["excerpts"][0]["text"] == (tmp_path / "big.txt").read_text()
    assert stage._admit({"id": "k", "claim": "small is read too",
                         "sources": [{"ref": "s0/0.1"}],
                         "detector": {"scope": "pytest", "confirm": "passed"}}) == (
        True, "admitted")
