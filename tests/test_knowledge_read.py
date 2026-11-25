import json
from pathlib import Path

import pytest

from tests.test_knowledge_workflow import _learn_source_knowledge
from tests.test_live_hooks import call, env, repo, store_for  # noqa: F401

CLAIM = "Source is observed"


@pytest.mark.parametrize("host,name,key", [("pi", "read", "path"), ("copilot", "view", "path")])
def test_a_card_reaches_each_host_after_read_and_stops_when_a_proof_changes(
        tmp_path, env, repo, monkeypatch, host, name, key):
    from tokeneconomizer.knowledge.stage import Knowledge, workspace_id
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode, Copilot, Pi
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    source_ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    stage = Knowledge.load(workspace_id(source_ctx.repo.label, repo), source_ctx.mech_dir)
    dest_ctx = LiveContext.build(Pi() if host == "pi" else Copilot(), repo, enabled)
    stage.save(dest_ctx.mech_dir)
    path = str(Path(repo) / "source.txt")
    out = _read(enabled, repo, "host1", path, host=host, name=name, key=key)
    card = json.dumps(out)
    assert CLAIM in card and "source and support are related" in card
    assert "source.txt: source" in card and "support.txt: support" in card
    (Path(repo) / "support.txt").write_text("changed\n")
    assert CLAIM not in json.dumps(_read(enabled, repo, "host2", path, host=host, name=name, key=key))


def _read(enabled, repo, sid, path, host=None, event="PostToolUse", name="Read", key="file_path"):
    return call(enabled, {"hook_event_name": event, "session_id": sid, "cwd": repo,
                          "tool_name": name, "tool_input": {key: path},
                          "tool_response": {"content": "observed"},
                          "tool_result": {"text_result_for_llm": "observed"}}, host)


def _prompt(enabled, repo, sid, text, host=None):
    return call(enabled, {"hook_event_name": "UserPromptSubmit", "session_id": sid,
                          "cwd": repo, "prompt": text}, host)


def _logged(enabled, repo):
    return [e for e in store_for(enabled, repo).read_lines("events.jsonl") if e["kind"] == "knowledge"]


def test_reading_a_covered_file_injects_its_knowledge_once_after_the_read(
        tmp_path, env, repo, monkeypatch):
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)   # loopguard is off
    source = str(Path(repo) / "source.txt")
    assert _read(enabled, repo, "r1", str(Path(repo) / "other.txt")) == {}
    out = _read(enabled, repo, "r1", source)
    assert CLAIM in json.dumps(out)
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    (entry,) = _logged(enabled, repo)
    assert (entry["signal"], entry["trigger"], entry["when"], entry["read_before"]) == (
        "source.txt", "read", "after_read", False)
    assert CLAIM not in json.dumps(_read(enabled, repo, "r1", source))      # once per session
    assert len(_logged(enabled, repo)) == 1


def test_a_file_read_earlier_in_the_session_is_flagged(tmp_path, env, repo, monkeypatch):
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    source = str(Path(repo) / "source.txt")
    Path(source).write_text("changed\n")                # its proof fails: nothing to inject yet
    assert _read(enabled, repo, "r2", source) == {}
    Path(source).write_text("observed\n")
    out = _read(enabled, repo, "r2", "./source.txt")
    assert CLAIM in json.dumps(out)
    assert _logged(enabled, repo)[-1]["read_before"] is True


def test_a_prompt_naming_a_signal_injects_that_knowledge(
        tmp_path, env, repo, monkeypatch):
    """A request naming a Knowledge's file brings it, on a host whose prompt hook reaches the
    model; a request that shares no signal, and a host without prompt context, bring nothing."""
    from tokeneconomizer.plugin.hosts import ClaudeCode
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)   # loopguard is off
    assert _prompt(enabled, repo, "n1", "rename the widget") == {}
    out = _prompt(enabled, repo, "p1", "check source.txt")
    assert CLAIM in json.dumps(out)
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    (entry,) = _logged(enabled, repo)
    assert (entry["signal"], entry["trigger"], entry["read_before"]) == (
        "source.txt", "prompt", False)
    with monkeypatch.context() as m:
        m.setattr(ClaudeCode, "prompt_context", False)
        assert _prompt(enabled, repo, "p2", "check source.txt") == {}
    assert len(_logged(enabled, repo)) == 1


def test_a_knowledge_given_by_the_prompt_is_not_given_again_by_the_read(
        tmp_path, env, repo, monkeypatch):
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    _prompt(enabled, repo, "r3", "check source.txt")
    assert CLAIM not in json.dumps(_read(enabled, repo, "r3", str(Path(repo) / "source.txt")))
    assert [e["trigger"] for e in _logged(enabled, repo)] == ["prompt"]
    # and the other way round
    _read(enabled, repo, "r4", str(Path(repo) / "source.txt"))
    assert CLAIM not in json.dumps(_prompt(enabled, repo, "r4", "check source.txt"))


def test_card_respects_budget_left_by_native_facts(tmp_path, env, repo, monkeypatch):
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    store = store_for(enabled, repo)
    store.write("injection.json", {"rendered": "# native\n- A\n- B\n- C\n- D\n"})
    both = dict(enabled, TE_MICROSKILLS="envfacts")
    call(both, {"hook_event_name": "SessionStart", "source": "startup", "session_id": "budget", "cwd": repo})
    assert CLAIM not in json.dumps(_read(both, repo, "budget", str(Path(repo) / "source.txt")))


def test_a_host_not_verified_and_every_other_case_inject_nothing(tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin.hosts import ClaudeCode
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    source = str(Path(repo) / "source.txt")
    # A host not verified to accept context after a tool call gets nothing.
    with monkeypatch.context() as m:
        m.setattr(ClaudeCode, "tool_context", False, raising=False)
        assert _read(enabled, repo, "u1", source) == {}
    # A failed read, a shadow run and a disabled mechanism inject nothing.
    assert _read(enabled, repo, "f1", source, event="PostToolUseFailure") == {}
    assert _read(dict(enabled, TE_SHADOW="on"), repo, "s1", source) == {}
    assert _read(dict(enabled, TE_KNOWLEDGE="off"), repo, "o1", source) == {}
    # A selection error leaves the hook's output empty.
    from tokeneconomizer.knowledge.stage import Knowledge
    with monkeypatch.context() as m:
        m.setattr(Knowledge, "load", lambda *a, **kw: 1 / 0)
        assert _read(enabled, repo, "e1", source) == {}


def test_a_read_after_a_clear_gives_the_knowledge_again(tmp_path, env, repo, monkeypatch):
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    source = str(Path(repo) / "source.txt")
    _read(enabled, repo, "k1", source)
    call(enabled, {"hook_event_name": "SessionStart", "source": "clear", "session_id": "k1", "cwd": repo})
    assert CLAIM in json.dumps(_read(enabled, repo, "k1", source))
    assert _logged(enabled, repo)[-1]["read_before"] is False


def test_a_prompt_flags_the_knowledge_files_read_earlier_in_the_session(
        tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin.hosts import ClaudeCode
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    source = str(Path(repo) / "source.txt")

    def prompt(sid):
        out = _prompt(enabled, repo, sid, "check source.txt")
        assert CLAIM in json.dumps(out)
        entry = _logged(enabled, repo)[-1]
        assert entry["trigger"] == "prompt"
        return entry["read_before"]
    assert prompt("p1") is False
    # A host whose read cannot inject still reports the read, and the flag follows it.
    with monkeypatch.context() as m:
        m.setattr(ClaudeCode, "tool_context", False, raising=False)
        assert _read(enabled, repo, "p2", source) == {}
    assert prompt("p2") is True


def test_a_later_read_flags_the_file_read_earlier_on_an_unverified_host(
        tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin.hosts import ClaudeCode
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    source = str(Path(repo) / "source.txt")

    def read_before(sid):
        out = _read(enabled, repo, sid, source)
        assert CLAIM in json.dumps(out)
        entry = _logged(enabled, repo)[-1]
        assert entry["trigger"] == "read"
        return entry["read_before"]
    assert read_before("p1") is False
    # A host whose read cannot inject still reports the read, and the flag follows it.
    with monkeypatch.context() as m:
        m.setattr(ClaudeCode, "tool_context", False, raising=False)
        assert _read(enabled, repo, "p2", source) == {}
    assert read_before("p2") is True
