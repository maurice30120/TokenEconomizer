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


def _learn_source_knowledge(tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin import sidecall
    source = Path(repo) / "source.txt"
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
    return enabled


def test_a_knowledge_is_injected_once_per_session(tmp_path, env, repo, monkeypatch):
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    sid = "once"

    def start(source, host=None):
        call(enabled, {"hook_event_name": "SessionStart", "source": source, "session_id": sid, "cwd": repo}, host)

    def prompt(text="please check source.txt", host=None):
        return "Source is observed" in json.dumps(call(enabled, {
            "hook_event_name": "UserPromptSubmit", "session_id": sid, "cwd": repo, "prompt": text}, host))
    start("startup")
    assert prompt()
    assert not prompt("and source.txt again")
    assert not prompt("source.txt once more")
    start("resume")                       # Claude replays its context: nothing again
    assert not prompt()
    start("clear")
    assert prompt()
    assert not prompt()
    start("compact")
    assert prompt()
    # Another session is not affected by this one's memory.
    sid = "other-session"
    start("startup")
    assert prompt()


def test_a_resumed_session_keeps_the_knowledge_it_was_given(tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin.hosts import ClaudeCode
    # Copilot rebuilds a resumed conversation without its start context, but the Knowledge came
    # as prompt context, which stays in the history: it is not given again.
    monkeypatch.setattr(ClaudeCode, "keeps_start_context", False)
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)

    def send(event, **kw):
        return json.dumps(call(enabled, dict({"hook_event_name": event, "session_id": "c1", "cwd": repo}, **kw)))
    send("SessionStart", source="new")
    assert "Source is observed" in send("UserPromptSubmit", prompt="look at source.txt")
    send("SessionStart", source="resume")
    assert "Source is observed" not in send("UserPromptSubmit", prompt="look at source.txt")
    send("SessionStart", source="clear")
    assert "Source is observed" in send("UserPromptSubmit", prompt="look at source.txt")


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
    start = {"hook_event_name": "SessionStart", "source": "startup", "session_id": "new", "cwd": repo}
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "new", "cwd": repo,
               "prompt": "please check source.txt"}
    assert "Source is observed" not in json.dumps(call(enabled, start))
    from tests.test_live_hooks import store_for
    def logged():
        return [e for e in store_for(enabled, repo).read_lines("events.jsonl") if e["kind"] == "knowledge"]
    assert logged() == []
    assert "Source is observed" in json.dumps(call(enabled, payload))
    (entry,) = logged()
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    (stored,) = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir).facts
    assert (entry["knowledge_id"], entry["signal"], entry["trigger"], entry["session_id"]) == (stored, "source.txt", "prompt", "new")
    assert call(enabled, dict(payload, session_id="unrelated", prompt="rename the widget")) == {}
    assert "Source is observed" in json.dumps(call(enabled, dict(payload, session_id="path", prompt="open ./src/../source.txt now")))
    assert call(enabled, dict(payload, session_id="near", prompt="open resource.txt and source.txt.bak")) == {}
    other = tmp_path / "other"
    (other / ".git").mkdir(parents=True)
    (other / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (other / ".git" / "config").write_text('[remote "origin"]\n url = https://github.com/acme/widget.git\n')
    (other / "source.txt").write_text("observed\n")
    assert "Source is observed" not in json.dumps(call(enabled, dict(payload, cwd=str(other), session_id="other")))
    ctx.store.write("injection.json", {"rendered": "# native\n- Native fact\n"})
    together = dict(enabled, TE_MICROSKILLS="envfacts")
    text = json.dumps(call(together, dict(start, session_id="both")))
    assert "Native fact" in text and "Source is observed" not in text
    assert "Source is observed" in json.dumps(call(together, dict(payload, session_id="both")))
    ctx.store.write("injection.json", {"rendered": "# native\n- A\n- B\n- C\n- D\n"})
    text = json.dumps(call(together, dict(start, session_id="budget")))
    assert "Source is observed" not in text and "- A" in text
    assert call(together, dict(payload, session_id="budget")) == {}
    # No hook output reaches the model on a host without prompt context: no Knowledge there.
    from tokeneconomizer.plugin.hosts import ClaudeCode as Claude
    with monkeypatch.context() as m:
        m.setattr(Claude, "prompt_context", False)
        assert call(enabled, dict(payload, session_id="mute")) == {}
    # A selection error leaves the output empty: the hook fails open.
    with monkeypatch.context() as m:
        m.setattr(Knowledge, "load", lambda *a, **kw: 1 / 0)
        assert call(enabled, dict(payload, session_id="broken")) == {}
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
    before = len(logged())
    assert "Source is observed" not in json.dumps(call(enabled, dict(payload, session_id="forgotten")))
    assert len(logged()) == before
    assert command("unforget", fid) == 0
    assert "Source is observed" in json.dumps(call(enabled, dict(payload, session_id="restored")))
    source.write_text("changed\n")
    before = len(logged())
    assert "Source is observed" not in json.dumps(call(enabled, dict(payload, session_id="next")))
    assert len(logged()) == before
    assert "Source is observed" not in json.dumps(call(dict(enabled, TE_KNOWLEDGE="off"), dict(payload, session_id="off")))

    # A writer holds the same lock while a new hook tries to read the Knowledge.
    # Its removal must be visible before the hook can inject it.
    import copy
    import threading
    source.write_text("observed\n")
    stage = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
    first = next(iter(stage.facts))
    stage.facts["second"] = copy.deepcopy(stage.facts[first])
    stage.facts["second"].spec.update(id="second", claim="second claim", injection="second note")
    stage.facts["second"].injection = "second note"
    stage.save(ctx.mech_dir)
    assert "second note" in json.dumps(call(enabled, dict(payload, session_id="before-race")))
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
    assert "second note" not in output[0]
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


def test_a_knowledge_about_several_files_holds_while_all_of_them_do(tmp_path, monkeypatch):
    from tokeneconomizer.microskills import distiller
    monkeypatch.setattr(distiller, "PROPOSE_EVERY", 3)
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text(f"{name} observed\n")
    candidates = [{"id": "both", "claim": "a and b agree", "sources": [{"source": "a.txt"}, {"source": "b.txt"}],
                   "source_session": "s1", "cite": ["s0", "s1"],
                   "detector": {"scope": "pytest", "confirm": "passed"}}]
    stage = Knowledge("repo", runner=lambda *args: (json.dumps({"facts": candidates}), 0))
    stage.workspace = tmp_path
    def session(i):
        path = tmp_path / f"several{i}.jsonl"
        reads = [(f"r{n}", tmp_path / name) for n, name in enumerate(("a.txt", "b.txt"))]
        events = [{"type": "assistant", "message": {"content": [
            *({"type": "tool_use", "id": rid, "name": "Read", "input": {"file_path": str(file)}} for rid, file in reads),
            {"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}}]}}]
        for rid, file in reads:
            text = file.read_text()
            events.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": rid, "content": text}]},
                           "toolUseResult": {"type": "text", "file": {"filePath": str(file), "content": text, "startLine": 1, "numLines": 1, "totalLines": 1}}})
        events.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}})
        path.write_text("\n".join(map(json.dumps, events)))
        stage.update(path, iid=f"s{i}")
    for i in range(5):
        session(i)
    assert "a and b agree" in stage.render()
    stage.save(tmp_path)
    stage = Knowledge.load("repo", tmp_path)
    stage.workspace = tmp_path
    fact = next(iter(stage.facts.values()))
    assert {s for s, _ in stage.signals(fact)} == {"a.txt", "b.txt"}
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


def test_the_cli_shows_the_scope_a_partial_knowledge_really_read(tmp_path, env, repo,
                                                                 monkeypatch, capsys):
    """Story 4: what a partial read actually returned stays inspectable, not just its source."""
    from pathlib import Path
    from tokeneconomizer.plugin import cli
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    root = Path(repo)
    (root / "source.py").write_bytes(SOURCE)
    args = {"path": "source.py", "offset": 2, "limit": 1}
    text = pi_read(SOURCE, 2, 1)
    captures = capture_read(root, args, text)
    ctx = LiveContext.build(ClaudeCode(), repo, env)
    stage = Knowledge(workspace_id(ctx.repo.label, ctx.repo.root))
    stage.workspace, stage.host = root, "pi"
    for i in range(2):
        pi, trace = tmp_path / f"cli{i}.jsonl", tmp_path / f"clitrace{i}.jsonl"
        reads_session(pi, root, [("r", args, text, False)])
        claude_trace(trace)
        stage.update(trace, iid=f"s{i}", observed_transcript=pi, captures=captures)
    assert stage._admit(partial_candidate()) == (True, "admitted")
    stage.save(ctx.mech_dir)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert cli.main(["--host", "claude", "--cwd", repo, "microskills"]) == 0
    out = capsys.readouterr().out
    assert "source=source.py session=s1" in out
    assert 'observed={"reads": [{"lines": 1, "offset": 2}], "total_lines": 7}' in out


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


def learn_knowledge(tmp_path, env, repo, monkeypatch, files, candidates):
    """Learn Knowledge through five live sessions that read every file and pass a test run."""
    from tokeneconomizer.plugin import sidecall
    paths = {}
    for name, content in files.items():
        paths[name] = Path(repo) / name
        paths[name].parent.mkdir(parents=True, exist_ok=True)
        paths[name].write_text(content)
    facts = [dict(c, source_session="s1", cite=["s0", "s1"], detector={"scope": "pytest", "confirm": "passed"})
             for c in candidates]
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
        events = [{"type": "assistant", "message": {"content": uses}}, *results,
                  {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}}]
        tp = tmp_path / f"rank{i}.jsonl"
        tp.write_text("\n".join(map(json.dumps, events)))
        run_session(enabled, repo, f"s{i}", str(tp))
    return enabled


def prompt(enabled, repo, sid, text, **limits):
    env = dict(enabled, **limits)
    return json.dumps(call(env, {"hook_event_name": "UserPromptSubmit", "session_id": sid, "cwd": repo, "prompt": text}))


def test_a_small_budget_keeps_the_stronger_match_then_the_higher_firing_rate(tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    body = "observed\n"
    names = ["pkg/deep.txt", "lib/full.txt", "lib/twin.txt", "lib/rare.txt"]
    enabled = learn_knowledge(
        tmp_path, env, repo, monkeypatch, {n: body for n in names},
        [{"id": n.split("/")[1][:4], "claim": f"{n} is observed", "source": n} for n in names])
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    one = dict(TE_MICROSKILLS_MAX_FACTS="1")
    # Registration order puts the file-name match first; the full path is the stronger match.
    assert "lib/full.txt is observed" in prompt(enabled, repo, "b", "read deep.txt and lib/full.txt", **one)
    assert "lib/full.txt is observed" in prompt(enabled, repo, "c", "lib/full.txt then deep.txt", **one)
    # Equal matches: the higher firing rate first, registration order when rates tie.
    both = "lib/twin.txt and lib/rare.txt"
    assert "lib/twin.txt is observed" in prompt(enabled, repo, "d", both, **one)
    stage = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
    by_source = {f.spec["source"]: f for f in stage.facts.values()}
    rare, twin = by_source["lib/rare.txt"].life, by_source["lib/twin.txt"].life
    rare.fire_num, rare.fire_den, twin.fire_num, twin.fire_den = 9, 10, 5, 10
    stage.save(ctx.mech_dir)
    assert "lib/rare.txt is observed" in prompt(enabled, repo, "e", both, **one)
    # The shared budget with native facts is still respected.
    ctx.store.write("injection.json", {"rendered": "# native\n- A\n- B\n"})
    together = dict(enabled, TE_MICROSKILLS="envfacts")
    start = {"hook_event_name": "SessionStart", "source": "startup", "session_id": "n", "cwd": repo}
    assert "- B" in json.dumps(call(dict(together, TE_MICROSKILLS_MAX_FACTS="3"), start))
    text = prompt(together, repo, "n", "deep.txt lib/full.txt lib/twin.txt", TE_MICROSKILLS_MAX_FACTS="3")
    assert text.count("is observed") == 1 and "lib/full.txt is observed" in text


def test_a_symbol_named_in_the_prompt_outranks_a_file_match(tmp_path, env, repo, monkeypatch):
    pytest.importorskip("tree_sitter_language_pack")
    code = "def target():\n    return 1\n"
    enabled = learn_knowledge(
        tmp_path, env, repo, monkeypatch, {"first.txt": "observed\n", "second.py": code},
        [{"id": "file", "claim": "first.txt is observed", "source": "first.txt"},
         {"id": "sym", "claim": "target returns one", "source": "second.py", "symbol": "target"}])
    text = prompt(enabled, repo, "a", "in first.txt look at target in second.py", TE_MICROSKILLS_MAX_FACTS="1")
    assert "target returns one" in text and "first.txt is observed" not in text


def test_a_symbol_alone_in_the_prompt_does_not_bring_its_knowledge_without_its_file(tmp_path, env, repo, monkeypatch):
    pytest.importorskip("tree_sitter_language_pack")
    enabled = learn_knowledge(
        tmp_path, env, repo, monkeypatch, {"second.py": "def run():\n    return 1\n"},
        [{"id": "sym", "claim": "run returns one", "source": "second.py", "symbol": "run"}])
    # A common name says nothing about which `run` the request means.
    assert "run returns one" not in prompt(enabled, repo, "a", "please run the tests")
    # The file the symbol lives in is the hint that it is this one, by path or by file name.
    assert "run returns one" in prompt(enabled, repo, "b", "run in second.py")
    assert "run returns one" in prompt(enabled, repo, "c", "second.py: please run it")
    # The file alone is not the symbol: that Knowledge reaches the agent when it reads the file.
    assert "run returns one" not in prompt(enabled, repo, "d", "look at second.py")
