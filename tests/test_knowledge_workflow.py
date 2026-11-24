import json

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
