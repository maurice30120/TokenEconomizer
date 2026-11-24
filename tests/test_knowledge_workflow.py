import json

import pytest

from tokeneconomizer.knowledge.stage import Knowledge, workspace_id
from tokeneconomizer.plugin.config import load_config
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
