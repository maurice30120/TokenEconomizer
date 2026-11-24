import json

import pytest

from tokeneconomizer.knowledge.stage import Knowledge, workspace_id
from tokeneconomizer.plugin.config import load_config
from tests.test_knowledge_pi import SOURCE, capture_read, pi_read, reads_session
from tests.test_live_hooks import call, env, repo, run_session  # noqa: F401


def test_knowledge_is_independent_and_disabled_by_default(tmp_path):
    assert not load_config(str(tmp_path), env={}).knowledge
    cfg = load_config(str(tmp_path), env={"TE_KNOWLEDGE": "on", "TE_MICROSKILLS": "off"})
    assert cfg.knowledge and cfg.microskills == "off"


def test_hook_uses_current_proof_even_when_session_cache_is_warm(tmp_path, env, repo, monkeypatch, capsys):
    from tokeneconomizer.plugin import sidecall
    source = __import__("pathlib").Path(repo) / "source.txt"
    source.write_text("observed\n")
    candidate = {"id": "k", "claim": "Source is observed", "source": "source.txt", "source_session": "s1", "cite": ["s0", "s1"], "detector": {"scope": "pytest", "confirm": "passed"}}
    monkeypatch.setattr(sidecall, "runner_for", lambda *a, **kw: lambda *a: (json.dumps({"facts": [candidate]}), 0))
    enabled = dict(env, TE_KNOWLEDGE="on", TE_MICROSKILLS="off", TE_LOOPGUARD="off", TE_TOOLPRUNE="off")
    for i in range(5):
        tp = tmp_path / f"hook{i}.jsonl"
        events = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": str(source)}}, {"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r", "content": "     1→observed"}]}, "toolUseResult": {"type": "text", "file": {"filePath": str(source), "content": "observed\n", "startLine": 1, "numLines": 1, "totalLines": 1}}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}},
        ]
        tp.write_text("\n".join(map(json.dumps, events)))
        run_session(enabled, repo, f"s{i}", str(tp))
    payload = {"hook_event_name": "SessionStart", "source": "startup", "session_id": "new", "cwd": repo}
    assert "Source is observed" in json.dumps(call(enabled, payload))
    other = tmp_path / "other"
    (other / ".git").mkdir(parents=True)
    (other / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (other / ".git" / "config").write_text('[remote "origin"]\n url = https://github.com/acme/widget.git\n')
    (other / "source.txt").write_text("observed\n")
    assert "Source is observed" not in json.dumps(call(enabled, dict(payload, cwd=str(other), session_id="other")))
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    ctx.store.write("injection.json", {"rendered": "# native\n- Native fact\n"})
    together = dict(enabled, TE_MICROSKILLS="envfacts")
    text = json.dumps(call(together, dict(payload, session_id="both")))
    assert "Native fact" in text and "Source is observed" in text
    ctx.store.write("injection.json", {"rendered": "# native\n- A\n- B\n- C\n- D\n"})
    text = json.dumps(call(together, dict(payload, session_id="budget")))
    assert "Source is observed" not in text and "- A" in text
    saved = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
    fid = next(iter(saved.facts))
    from tokeneconomizer.plugin import cli
    for key, value in enabled.items():
        monkeypatch.setenv(key, value)
    def command(*args):
        return cli.main(["--host", "claude", "--cwd", repo, "microskills", *args])
    assert command() == 0
    output = capsys.readouterr().out
    assert fid in output and "rev=1" in output and "proof=valid" in output
    assert "source.txt" in output and "s1" in output
    assert command("forget", fid) == 0
    assert command() == 0
    output = capsys.readouterr().out
    assert fid in output and "source.txt" in output and "s1" in output and "forgotten" in output
    assert "Source is observed" not in json.dumps(call(enabled, dict(payload, session_id="forgotten")))
    assert command("unforget", fid) == 0
    assert "Source is observed" in json.dumps(call(enabled, dict(payload, session_id="restored")))
    source.write_text("changed\n")
    assert "Source is observed" not in json.dumps(call(enabled, dict(payload, session_id="next")))
    assert "Source is observed" not in json.dumps(call(dict(enabled, TE_KNOWLEDGE="off"), dict(payload, session_id="off")))

    # A writer holds the same lock while a new hook tries to resolve dependencies.
    # Its removal must be visible before the hook can inject the synthesis.
    import copy
    import threading
    source.write_text("observed\n")
    stage = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
    first = next(iter(stage.facts))
    stage.facts["second"] = copy.deepcopy(stage.facts[first])
    stage.facts["second"].spec["id"] = "second"
    composite = copy.deepcopy(stage.facts[first])
    composite.spec.update(id="synthesis", claim="combined", injection="combined",
                          dependencies=[{"id": first, "revision": 1}, {"id": "second", "revision": 1}])
    composite.spec.pop("proof", None)
    stage.facts["synthesis"] = composite
    stage.save(ctx.mech_dir)
    assert "combined" in json.dumps(call(enabled, dict(payload, session_id="before-race")))
    started = threading.Event()
    output = []
    def start_hook():
        started.set()
        output.append(json.dumps(call(enabled, dict(payload, session_id="during-race"))))
    with ctx.store.locked("mechanisms") as acquired:
        assert acquired
        thread = threading.Thread(target=start_hook)
        thread.start()
        assert started.wait(2)
        thread.join(0.2)
        assert thread.is_alive()
        del stage.facts["second"]
        stage.save(ctx.mech_dir)
    thread.join(5)
    assert not thread.is_alive()
    assert "combined" not in output[0]
    assert "Source is observed" in output[0]



def test_sessions_learn_then_revalidate_before_each_injection(tmp_path, monkeypatch):
    from tokeneconomizer.microskills import distiller
    monkeypatch.setattr(distiller, "PROPOSE_EVERY", 3)
    source = tmp_path / "source.txt"
    source.write_text("observed\n")
    def runner(prompt, model):
        return json.dumps({"facts": [{"id": "suggestion", "claim": "Source contains observed", "injection": "Source contains observed", "source": "source.txt", "source_session": "s1", "cite": ["s0", "s1"], "detector": {"scope": "pytest", "confirm": "passed"}}]}), 0
    stage = Knowledge("repo", runner=runner)
    stage.workspace = tmp_path
    def fold_session(i):
        path = tmp_path / f"s{i}.jsonl"
        events = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "read", "name": "Read", "input": {"file_path": str(source)}}, {"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "read", "content": "observed\n"}]}, "toolUseResult": {"type": "text", "file": {"filePath": str(source), "content": "observed\n", "startLine": 1, "numLines": 1, "totalLines": 1}}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}},
        ]
        path.write_text("\n".join(map(json.dumps, events)))
        stage.update(path, iid=f"s{i}")
    for i in range(5):
        fold_session(i)
    assert "Source contains observed" in stage.render()
    fid = next(k for k in stage.debug_row() if not k.startswith("_"))
    def revise(prompt, model):
        return json.dumps({"facts": [{"id": fid, "claim": "Revised observation", "source": "source.txt", "source_session": "s6", "cite": ["s5", "s6"], "detector": {"scope": "pytest", "confirm": "passed"}}]}), 0
    stage.runner = revise
    for i in range(5, 8):
        fold_session(i)
    assert not stage.render()
    assert stage.debug_row()[fid]["rev"] == 2
    for i in range(8, 12):
        fold_session(i)
    assert "Revised observation" in stage.render()
    source.write_text("changed\n")
    assert "Revised observation" not in stage.render()
    source.write_text("observed\n")
    assert "Revised observation" in stage.render()


def test_detector_revision_must_earn_injection_again(tmp_path, monkeypatch):
    from tokeneconomizer.microskills import distiller
    monkeypatch.setattr(distiller, "PROPOSE_EVERY", 3)
    source = tmp_path / "source.txt"
    source.write_text("observed\n")
    def runner(prompt, model):
        return json.dumps({"facts": [{"id": "suggestion", "claim": "Source contains observed", "injection": "Source contains observed", "source": "source.txt", "source_session": "s1", "cite": ["s0", "s1"], "detector": {"scope": "pytest", "confirm": "passed"}}]}), 0
    stage = Knowledge("repo", runner=runner)
    stage.workspace = tmp_path
    def fold_session(i):
        path = tmp_path / f"s{i}.jsonl"
        events = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "read", "name": "Read", "input": {"file_path": str(source)}}, {"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "read", "content": "observed\n"}]}, "toolUseResult": {"type": "text", "file": {"filePath": str(source), "content": "observed\n", "startLine": 1, "numLines": 1, "totalLines": 1}}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}},
        ]
        path.write_text("\n".join(map(json.dumps, events)))
        stage.update(path, iid=f"s{i}")
    for i in range(5):
        fold_session(i)
    assert "Source contains observed" in stage.render()
    fid = next(k for k in stage.debug_row() if not k.startswith("_"))
    def revise(prompt, model):
        return json.dumps({"facts": [{"id": fid, "claim": "Revised observation", "source": "source.txt", "source_session": "s6", "cite": ["s5", "s6"], "detector": {"scope": "pytest", "confirm": "passed"}}]}), 0
    # Changing only the contradiction detector is still a Knowledge revision.
    old = stage.facts[fid].spec
    def revise_detector(prompt, model):
        candidate = dict(old, detector=dict(old["detector"], contradict="failed"),
                         source_session="s6", cite=["s5", "s6"])
        return json.dumps({"facts": [candidate]}), 0
    stage.runner = revise_detector
    for i in range(5, 8):
        fold_session(i)
    assert not stage.render()
    assert stage.debug_row()[fid]["rev"] == 2
    for i in range(8, 12):
        fold_session(i)
    assert "Source contains observed" in stage.render()
    return


@pytest.mark.parametrize("parser_available", [True, False])
def test_symbol_requested_in_session_survives_unrelated_edits_and_fails_closed(tmp_path, monkeypatch, parser_available):
    if not parser_available:
        import tree_sitter_language_pack
        def unavailable(*args):
            raise LookupError("unavailable")
        monkeypatch.setattr(tree_sitter_language_pack, "get_parser", unavailable)
    source = tmp_path / "source.py"
    content = "def target():\n    return 1\n\ndef other():\n    return 2\n"
    source.write_text(content)
    candidate = {"id": "s", "claim": "Target returns one", "source": "source.py", "symbol": "target", "source_session": "s1", "cite": ["s0", "s1"], "detector": {"scope": "pytest", "confirm": "passed"}}
    stage = Knowledge("repo", runner=lambda *args: (json.dumps({"facts": [candidate]}), 0))
    stage.workspace = tmp_path
    for i in range(5):
        path = tmp_path / f"session{i}.jsonl"
        events = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": str(source)}}, {"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r", "content": content}]}, "toolUseResult": {"type": "text", "file": {"filePath": str(source), "content": content, "startLine": 1, "numLines": 5, "totalLines": 5}}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}}
        ]
        path.write_text("\n".join(map(json.dumps, events)))
        stage.update(path, iid=f"s{i}")
    assert "Target returns one" in stage.render()
    evidence = next(iter(stage.facts.values())).spec["proof"]
    assert evidence["kind"] == ("symbol" if parser_available else "file")
    if not parser_available:
        assert evidence["fallback"] == {"symbol": "target", "reason": "symbol-unresolvable"}
    source.write_text(content.replace("return 2", "return 3"))
    assert ("Target returns one" in stage.render()) == parser_available
    source.write_text(content.replace("return 1", "return 4"))
    assert not stage.render()


def test_composed_knowledge_follows_atomic_dependencies(tmp_path, monkeypatch):
    from tokeneconomizer.microskills import distiller
    monkeypatch.setattr(distiller, "PROPOSE_EVERY", 3)
    source = tmp_path / "source.txt"
    source.write_text("observed\n")
    candidates = [
        {"id": name, "claim": name, "source": "source.txt", "source_session": "s1",
         "cite": ["s0", "s1"], "detector": {"scope": "pytest", "confirm": "passed"}}
        for name in ("first", "second")
    ]
    stage = Knowledge("repo", runner=lambda *args: (json.dumps({"facts": candidates}), 0))
    stage.workspace = tmp_path
    def session(i):
        path = tmp_path / f"composed{i}.jsonl"
        events = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": str(source)}}, {"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r", "content": "observed\n"}]}, "toolUseResult": {"type": "text", "file": {"filePath": str(source), "content": "observed\n", "startLine": 1, "numLines": 1, "totalLines": 1}}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}},
        ]
        path.write_text("\n".join(map(json.dumps, events)))
        stage.update(path, iid=f"s{i}")
    for i in range(5):
        session(i)
    ids = list(stage.facts)
    assert len(ids) == 2
    candidates[:] = [{"id": "synthesis", "claim": "combined", "dependencies": ids,
                      "cite": ["s3", "s4"], "detector": {"scope": "pytest", "confirm": "passed"}}]
    for i in range(5, 11):
        session(i)
    assert "combined" in stage.render()
    stage.save(tmp_path)
    stage = Knowledge.load("repo", tmp_path)
    stage.workspace = tmp_path
    assert "combined" in stage.render()
    source.write_text("changed\n")
    assert "combined" not in stage.render()
    source.write_text("observed\n")
    assert "combined" in stage.render()
    composite_id = next(fid for fid in stage.facts if fid not in ids)
    stage.runner = lambda *args: (json.dumps({"facts": [{"id": "nested", "claim": "nested", "dependencies": [ids[0], composite_id], "cite": ["s8", "s9"], "detector": {"scope": "pytest", "confirm": "passed"}}]}), 0)
    for i in range(11, 14):
        session(i)
    assert all(f.claim != "nested" for f in stage.facts.values())
    stage.facts[ids[0]].spec["rev"] += 1
    assert "combined" not in stage.render()
    assert "second" in stage.render()
    del stage.facts[ids[0]]
    assert "combined" not in stage.render()


def test_paid_native_and_knowledge_share_one_proposal_budget(tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin import sidecall
    calls = []
    source = __import__("pathlib").Path(repo) / "source.txt"
    source.write_text("observed\n")
    detector = {"scope": "pytest", "confirm": "passed"}
    facts = [{"id": "native", "claim": "native claim", "cite": ["s0", "s1"], "detector": detector}]
    facts += [{"id": f"k{i}", "claim": f"knowledge {i}", "source": "source.txt",
               "source_session": "s1", "cite": ["s0", "s1"], "detector": detector}
              for i in range(4)]
    def runner(prompt, model):
        calls.append(prompt)
        return json.dumps({"facts": facts}), 5
    monkeypatch.setattr(sidecall, "runner_for", lambda *a, **kw: runner)
    enabled = dict(env, TE_KNOWLEDGE="on", TE_MICROSKILLS="distiller",
                   TE_LOOPGUARD="off", TE_TOOLPRUNE="off")
    for i in range(3):
        path = tmp_path / f"shared{i}.jsonl"
        events = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": str(source)}}, {"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r", "content": "observed\n"}]}, "toolUseResult": {"type": "text", "file": {"filePath": str(source), "content": "observed\n", "startLine": 1, "numLines": 1, "totalLines": 1}}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}},
        ]
        path.write_text("\n".join(map(json.dumps, events)))
        run_session(enabled, repo, f"s{i}", str(path))
    assert len(calls) == 1
    assert "observed_sources" in calls[0]
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    from tokeneconomizer.microskills.distiller import Distiller
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    native = Distiller.load(ctx.repo.label, ctx.mech_dir)
    knowledge = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
    assert len(native.facts) == 1
    assert len(knowledge.facts) == 3


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
        original_propose = Knowledge._maybe_propose
        attempts = []
        def fail_capture(self):
            if self.runner is not None:
                attempts.append(1)
                if failure == "capture_error" or len(attempts) == 2:
                    raise ValueError("invalid Knowledge context")
            return original_propose(self)
        monkeypatch.setattr(Knowledge, "_maybe_propose", fail_capture)
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
    args = {"path": "source.py", "offset": 2, "limit": 1}
    text = pi_read(SOURCE, 2, 1)
    captures = capture_read(tmp_path, args, text)
    stage = Knowledge("repo")
    stage.workspace, stage.host = tmp_path, "pi"
    for i in range(sessions):
        pi, trace = tmp_path / f"pi{i}.jsonl", tmp_path / f"trace{i}.jsonl"
        reads_session(pi, tmp_path, [("r", args, text, False)])
        claude_trace(trace)
        stage.update(trace, iid=f"s{i}", observed_transcript=pi, captures=captures)
    return stage, source


def partial_candidate(**fields):
    candidate = {"id": "alpha-one", "claim": "Alpha returns one", "source": "source.py",
                 "symbol": "alpha", "source_session": "s1", "cite": ["s0", "s1"],
                 "detector": {"scope": "pytest", "confirm": "passed"}}
    candidate.update(fields)
    return {k: v for k, v in candidate.items() if v is not None}


def test_partial_knowledge_admits_on_the_symbol_its_read_crossed(tmp_path):
    stage, _ = partial_stage(tmp_path)
    assert stage._admit(partial_candidate()) == (True, "admitted")
    spec = next(iter(stage.facts.values())).spec
    assert spec["proof"]["kind"] == "symbol" and spec["proof"]["symbol"] == "alpha"
    assert spec["provenance"] == {
        "session": "s1", "path": "source.py",
        "observed": {"reads": [{"offset": 2, "lines": 1}], "total_lines": 7}}


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
    observation = state["window"][-1]["_observations"]["source.py"]
    assert observation["content"] == "    return 1"
    assert observation["excerpt"].startswith("    return 1")
    assert observation["observed"]["total_lines"] == 7
    assert "proof" not in observation


def test_the_proposer_is_told_what_a_partial_source_can_support(tmp_path):
    stage, _ = partial_stage(tmp_path)
    prompts = []
    stage.runner = lambda prompt, model: (prompts.append(prompt) or '{"facts": []}', 0)
    stage._maybe_propose()
    assert "read only in part" in prompts[0]
    assert "observed_lines" in prompts[0]


def symbol_less_partial_stage(tmp_path, sessions=2):
    """A `Knowledge` fed Pi sessions that each read line 3 of `source.py`: a blank line."""
    source = tmp_path / "source.py"
    source.write_bytes(SOURCE)
    args = {"path": "source.py", "offset": 3, "limit": 1}
    text = pi_read(SOURCE, 3, 1)
    captures = capture_read(tmp_path, args, text)
    stage = Knowledge("repo")
    stage.workspace, stage.host = tmp_path, "pi"
    for i in range(sessions):
        pi, trace = tmp_path / f"blank{i}.jsonl", tmp_path / f"blanktrace{i}.jsonl"
        reads_session(pi, tmp_path, [("r", args, text, False)])
        claude_trace(trace)
        stage.update(trace, iid=f"s{i}", observed_transcript=pi, captures=captures)
    return stage, source


def test_a_partial_source_no_symbol_proves_is_not_offered_to_the_proposer(tmp_path):
    stage, _ = symbol_less_partial_stage(tmp_path)
    dg = stage._featurize({}, [])
    # the read crossed no declaration: nothing the proposer could propose survives admission
    assert dg["observed_sources"] == []
    # the observation is kept, so the refusal names the real reason and nothing else
    assert dg["_observations"]["source.py"]["symbols"] == {}
    assert stage._admit(partial_candidate(symbol="alpha")) == (False, "symbol-not-observed")
    assert not stage.facts
