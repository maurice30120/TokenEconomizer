import json
from pathlib import Path

from tests.test_knowledge_workflow import _learn_source_knowledge
from tests.test_live_hooks import call, env, repo, store_for  # noqa: F401

CLAIM = "Source is observed"


def _read(enabled, repo, sid, path, host=None, event="PostToolUse", name="Read", key="file_path"):
    return call(enabled, {"hook_event_name": event, "session_id": sid, "cwd": repo,
                          "tool_name": name, "tool_input": {key: path},
                          "tool_response": {"content": "observed"},
                          "tool_result": {"text_result_for_llm": "observed"}}, host)


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


def test_a_knowledge_given_by_the_prompt_is_not_given_again_by_the_read(
        tmp_path, env, repo, monkeypatch):
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    call(enabled, {"hook_event_name": "UserPromptSubmit", "session_id": "r3", "cwd": repo,
                   "prompt": "check source.txt"})
    assert CLAIM not in json.dumps(_read(enabled, repo, "r3", str(Path(repo) / "source.txt")))
    assert [e["trigger"] for e in _logged(enabled, repo)] == ["prompt"]
    # and the other way round
    _read(enabled, repo, "r4", str(Path(repo) / "source.txt"))
    out = call(enabled, {"hook_event_name": "UserPromptSubmit", "session_id": "r4", "cwd": repo,
                         "prompt": "check source.txt"})
    assert CLAIM not in json.dumps(out)


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
