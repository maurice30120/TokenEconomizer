"""The one seam that answers which workspace files a tool call names.

`Host.named_files` is the seam both callers share: the gate that admits Knowledge after a tool
call (`LiveController._reports_named`) and the recorder of what the session named
(`LiveController._knowledge_from_tool`). A mention is a Knowledge Signal found in the call's
text -- a symbol as a whole identifier, its path, or its bare file name -- whatever the tool:
a shell `grep` or `cat` naming a covered file, an edit or a write naming it, a host tool with
its own name for reading. The ranking is the prompt trigger's own matcher.
"""
import json
from pathlib import Path

import pytest

from tests.test_knowledge_workflow import _learn_source_knowledge, learn_knowledge
from tests.test_live_hooks import call, env, repo, store_for  # noqa: F401

STORAGE = "codetour/src/store/storage.ts"


def _signals(rel=STORAGE):
    """Nameable signals for one covered file, as `Knowledge.nameable` gives them."""
    return [("moveCurrentCodeTourForward", rel), (rel, rel)]


@pytest.mark.parametrize("payload,signals,cwd,root,expected", [
    # A file-reading tool names the covered file it read, by full path or by bare name.
    ({"tool_name": "Read", "tool_input": {"file_path": STORAGE}}, _signals(),
     "/w", "/w", [(STORAGE, 2)]),
    ({"tool_name": "read", "tool_input": {"path": "src/store/storage.ts"}}, _signals(),
     "/w/codetour", "/w", [(STORAGE, 1)]),
    ({"tool_name": "view", "tool_input": {"path": STORAGE}}, _signals(),
     "/w", "/w", [(STORAGE, 2)]),
    # A shell call names the covered file its command mentions, whatever the command.
    ({"tool_name": "bash", "tool_input": {"command": "grep -n observed storage.ts"}}, _signals(),
     "/w", "/w", [(STORAGE, 1)]),
    ({"tool_name": "bash", "tool_input": {"command": "sed -n '1,20p' storage.ts"}}, _signals(),
     "/w", "/w", [(STORAGE, 1)]),
    ({"tool_name": "bash", "tool_input": {"command": "cat storage.ts"}}, _signals(),
     "/w", "/w", [(STORAGE, 1)]),
    ({"tool_name": "bash", "tool_input": {"command": "ls storage.ts"}}, _signals(),
     "/w", "/w", [(STORAGE, 1)]),
    # A write and an edit name the file they touch, whatever key carries the path.
    ({"tool_name": "write", "tool_input": {"path": STORAGE, "content": "x = 1\n"}},
     _signals(), "/w", "/w", [(STORAGE, 2)]),
    ({"tool_name": "edit", "tool_input": {"path": STORAGE,
                                          "edits": [{"oldText": "a", "newText": "b"}]}},
     _signals(), "/w", "/w", [(STORAGE, 2)]),
    ({"tool_name": "Edit", "tool_input": {"file_path": STORAGE, "old_string": "a",
                                          "new_string": "b"}}, _signals(), "/w", "/w",
     [(STORAGE, 2)]),
])
def test_the_seam_names_every_call_that_mentions_a_signal(payload, signals, cwd, root, expected):
    from tokeneconomizer.plugin.hosts import Host
    host = Host()
    p = dict(payload, hook_event_name="PostToolUse", tool_response={"content": "ok"})
    assert host.named_files(p, signals, cwd=cwd, root=root) == expected


def test_the_seam_names_nothing_for_a_call_that_mentions_nothing_a_failure_or_a_missing_path():
    from tokeneconomizer.plugin.hosts import Host
    host = Host()
    base = {"hook_event_name": "PostToolUse", "tool_response": {"content": "ok"}}
    signals = _signals()
    # A call that names nothing covered names nothing.
    assert host.named_files(dict(base, tool_name="bash",
                                 tool_input={"command": "git status"}),
                            signals, cwd="/w", root="/w") == []
    # A failed call names nothing, whatever its text.
    assert host.named_files(dict(base, tool_name="read", tool_input={"path": "storage.ts"},
                                 tool_response={"content": "no", "isError": True}),
                            signals, cwd="/w", root="/w") == []
    # A read whose path lies outside the workspace names nothing, even when the bare name
    # matches a covered file: that mention is ignored.
    assert host.named_files(dict(base, tool_name="read",
                                 tool_input={"path": "../outside/storage.ts"}),
                            signals, cwd="/w", root="/w") == []


def test_the_seam_ranks_a_mention_with_the_prompt_triggers_matcher(monkeypatch):
    """A symbol as a whole identifier outranks the file by its full path, which outranks the
    bare file name -- exactly as it does for a prompt; the matcher runs on the call's own text,
    never on a parsed command."""
    import tokeneconomizer.knowledge.stage as stage_mod
    from tokeneconomizer.plugin.hosts import Host
    seen = []
    real = stage_mod.match_strength

    def recording_matcher(text, signal):
        seen.append((text, signal))
        return real(text, signal)

    monkeypatch.setattr(stage_mod, "match_strength", recording_matcher)
    host = Host()
    base = {"hook_event_name": "PostToolUse", "tool_response": {"content": "ok"}}

    def call(command):
        return host.named_files(dict(base, tool_name="bash",
                                     tool_input={"command": command}), _signals(),
                                cwd="/w", root="/w")
    assert call("grep moveCurrentCodeTourForward storage.ts") == [(STORAGE, 3)]
    assert call("grep -n x codetour/src/store/storage.ts") == [(STORAGE, 2)]
    assert call("grep -n x storage.ts") == [(STORAGE, 1)]
    # The matcher saw the call's own text, never a parsed command.
    assert all(text.endswith("storage.ts") and "grep" in text for text, _ in seen)


def test_the_read_tool_names_live_only_in_the_one_seam():
    """No second list of tool names survives in the plugin: the gate and the recorder both take
    their answer from `Host.named_files`, nowhere else."""
    plugin = Path(__file__).resolve().parents[1] / "tokeneconomizer" / "plugin"
    needle = '"Read", "read", "view"'
    hits = sum(p.read_text().count(needle) for p in plugin.rglob("*.py"))
    assert hits == 1


def test_nameable_pairs_each_source_its_symbol_and_its_file(
        tmp_path, env, repo, monkeypatch):
    """A symbol contract is nameable by its symbol and by its file; a file contract by its file."""
    pytest.importorskip("tree_sitter_language_pack")
    from tokeneconomizer.knowledge.stage import Knowledge, workspace_id
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    enabled = learn_knowledge(
        tmp_path, env, repo, monkeypatch,
        {"first.txt": "observed\n", "second.py": "def target():\n    return 1\n"},
        [{"id": "file", "claim": "first.txt is observed", "source": "first.txt"},
         {"id": "sym", "claim": "target returns one", "source": "second.py", "symbol": "target"}])
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    stage = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
    assert stage.nameable() == [("first.txt", "first.txt"), ("target", "second.py"),
                                ("second.py", "second.py")]


# ---- the trigger, end to end, on the campaign's own call shapes -----------------------------
def _pi_knowledge(tmp_path, env, repo, monkeypatch):
    """The learned card, copied into the Pi host's mechanism state (as the campaign had it)."""
    from tokeneconomizer.knowledge.stage import Knowledge, workspace_id
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode, Pi
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    source_ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    stage = Knowledge.load(workspace_id(source_ctx.repo.label, repo), source_ctx.mech_dir)
    stage.save(LiveContext.build(Pi(), repo, enabled).mech_dir)
    return enabled


@pytest.mark.parametrize("tool,args", [
    ("bash", {"command": "grep -n observed source.txt"}),
    ("bash", {"command": "sed -n '1p' source.txt"}),
    ("bash", {"command": "cat source.txt"}),
    # The campaign's own shell shape (run 01/07, which received no card on it): a `wc -l`
    # naming the covered file, from the real trace.
    ("bash", {"command": "cd /workspace && ls && echo \"---\" && wc -l source.txt"}),
    ("write", {"path": "source.txt", "content": "observed\n"}),
    ("edit", {"path": "source.txt", "edits": [{"oldText": "a", "newText": "b"}]}),
])
def test_a_call_that_names_a_covered_file_gets_its_knowledge_after_the_result(
        tmp_path, env, repo, monkeypatch, tool, args):
    enabled = _pi_knowledge(tmp_path, env, repo, monkeypatch)
    out = call(enabled, {"hook_event_name": "PostToolUse", "session_id": "k1", "cwd": repo,
                         "tool_name": tool, "tool_input": args, "tool_use_id": "c1",
                         "tool_response": {"content": "ok"}}, "pi")
    assert "Source is observed" in json.dumps(out)
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    (entry,) = [e for e in store_for(enabled, repo, "pi").read_lines("events.jsonl")
                if e["kind"] == "knowledge"]
    assert (entry["signal"], entry["trigger"], entry["when"], entry["tool"]) == (
        "source.txt", "tool", "after_call", tool)


def test_a_call_that_names_nothing_covered_a_failed_call_a_subagent_and_a_shadow_inject_nothing(
        tmp_path, env, repo, monkeypatch):
    enabled = _pi_knowledge(tmp_path, env, repo, monkeypatch)
    base = {"hook_event_name": "PostToolUse", "session_id": "k2", "cwd": repo,
            "tool_name": "bash", "tool_input": {"command": "grep -n observed source.txt"},
            "tool_response": {"content": "ok"}}
    assert call(enabled, dict(base, tool_input={"command": "git status"}), "pi") == {}
    assert call(enabled, dict(base, hook_event_name="PostToolUseFailure"), "pi") == {}
    assert call(enabled, dict(base, agent_id="sub-1"), "pi") == {}
    assert call(dict(enabled, TE_SHADOW="on"), base, "pi") == {}
    assert not [e for e in store_for(enabled, repo, "pi").read_lines("events.jsonl")
                if e["kind"] == "knowledge"]


def test_a_replayed_hook_injects_nothing_and_the_card_is_given_once(
        tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.controller import LiveController
    from tokeneconomizer.plugin.hosts import Pi
    enabled = _pi_knowledge(tmp_path, env, repo, monkeypatch)
    payload = {"hook_event_name": "PostToolUse", "session_id": "k3", "cwd": repo,
               "tool_name": "bash", "tool_input": {"command": "grep -n observed source.txt"},
               "tool_use_id": "c1", "tool_response": {"content": "ok"}}
    ctx = LiveContext.build(Pi(), repo, enabled)
    first = LiveController(ctx, payload)._knowledge_from_tool()
    assert "Source is observed" in json.dumps(first)
    replayed = LiveController(ctx, payload)
    replayed.replaying = True
    assert replayed._knowledge_from_tool() == {}
    again = LiveController(ctx, payload)._knowledge_from_tool()
    assert again == {}          # already given: once per session


def test_an_invalid_contract_excludes_the_card_whatever_the_call_names(
        tmp_path, env, repo, monkeypatch):
    """The mention is the trigger, not the proof: a card whose contract no longer holds is
    dropped at injection time, as it always was."""
    enabled = _pi_knowledge(tmp_path, env, repo, monkeypatch)
    Path(repo, "support.txt").write_text("changed\n")     # one of the card's two sources
    out = call(enabled, {"hook_event_name": "PostToolUse", "session_id": "k5", "cwd": repo,
                         "tool_name": "bash", "tool_use_id": "c1",
                         "tool_input": {"command": "grep -n observed source.txt"},
                         "tool_response": {"content": "ok"}}, "pi")
    assert out == {}
    assert not [e for e in store_for(enabled, repo, "pi").read_lines("events.jsonl")
                if e["kind"] == "knowledge"]


def test_a_selection_error_leaves_the_hook_output_empty(
        tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.knowledge.stage import Knowledge
    enabled = _pi_knowledge(tmp_path, env, repo, monkeypatch)
    with monkeypatch.context() as m:
        m.setattr(Knowledge, "load", lambda *a, **kw: 1 / 0)
        out = call(enabled, {"hook_event_name": "PostToolUse", "session_id": "k4",
                             "cwd": repo, "tool_name": "bash",
                             "tool_input": {"command": "grep -n observed source.txt"},
                             "tool_response": {"content": "ok"}}, "pi")
        assert out == {}


def test_a_read_still_injects_and_logs_exactly_as_before(tmp_path, env, repo, monkeypatch):
    """The widened trigger leaves the read path untouched: same injection, same log fields."""
    enabled = _pi_knowledge(tmp_path, env, repo, monkeypatch)
    source = str(Path(repo) / "source.txt")
    out = call(enabled, {"hook_event_name": "PostToolUse", "session_id": "r1", "cwd": repo,
                         "tool_name": "Read", "tool_input": {"file_path": source},
                         "tool_response": {"content": "observed"},
                         "tool_result": {"text_result_for_llm": "observed"}}, "pi")
    assert "Source is observed" in json.dumps(out)
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    (entry,) = [e for e in store_for(enabled, repo, "pi").read_lines("events.jsonl")
                if e["kind"] == "knowledge"]
    assert (entry["signal"], entry["trigger"], entry["when"], entry["tool"],
            entry["read_before"]) == ("source.txt", "tool", "after_call", "Read", False)


def test_the_session_list_says_named_and_an_older_files_read_state_still_loads(
        tmp_path, env, repo, monkeypatch):
    """The record claims no read that did not happen: the session keeps `files_named`, and a
    pre-change state whose list holds `files_read` is read as it was."""
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.controller import LiveController
    from tokeneconomizer.plugin.hosts import Pi
    enabled = _pi_knowledge(tmp_path, env, repo, monkeypatch)
    ctx = LiveContext.build(Pi(), repo, enabled)
    payload = {"hook_event_name": "PostToolUse", "session_id": "k6", "cwd": repo,
               "tool_name": "bash", "tool_use_id": "c1",
               "tool_input": {"command": "grep -n observed source.txt"},
               "tool_response": {"content": "ok"}}
    LiveController(ctx, payload)._knowledge_from_tool()
    doc = ctx.store.read("sessions/k6.json")
    assert doc.get("files_named") == ["source.txt"] and "files_read" not in doc
    # A pre-change state file is read as it was and migrated on the next write.
    ctx.store.write("sessions/k7.json",
                    {"session_id": "k7", "files_read": ["source.txt"]})
    prompt = {"hook_event_name": "UserPromptSubmit", "session_id": "k7", "cwd": repo,
              "prompt": "check source.txt"}
    LiveController(ctx, prompt).user_prompt()
    assert ctx.store.read("sessions/k7.json").get("files_read") == ["source.txt"]
    LiveController(ctx, dict(payload, session_id="k7"))._knowledge_from_tool()  # migrated
    doc = ctx.store.read("sessions/k7.json")
    assert doc.get("files_named") == ["source.txt"] and "files_read" not in doc
