import json
from pathlib import Path

import pytest

from tests.test_knowledge_workflow import _learn_source_knowledge, learn_knowledge
from tests.test_live_hooks import call, env, repo, store_for, write_session  # noqa: F401

CLAIM = "Source is observed"


@pytest.mark.parametrize("host,name,key", [("pi", "read", "path"), ("copilot", "view", "path")])
def test_a_card_reaches_each_host_after_read_and_stops_when_a_proof_changes(
        tmp_path, env, repo, monkeypatch, host, name, key):
    from tokeneconomizer.knowledge.stage import Knowledge
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode, Copilot, Pi
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    source_ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    stage = Knowledge.load(source_ctx.repo.label, source_ctx.mech_dir)
    dest_ctx = LiveContext.build(Pi() if host == "pi" else Copilot(), repo, enabled)
    stage.save(dest_ctx.mech_dir)
    path = str(Path(repo) / "source.txt")
    out = _read(enabled, repo, "host1", path, host=host, name=name, key=key)
    card = json.dumps(out)
    assert CLAIM in card
    (Path(repo) / "support.txt").write_text("changed\n")
    assert CLAIM not in json.dumps(_read(enabled, repo, "host2", path, host=host, name=name, key=key))


def _read(enabled, repo, sid, path, host=None, event="PostToolUse", name="Read", key="file_path",
          call_id=None, **inputs):
    return call(enabled, {"hook_event_name": event, "session_id": sid, "cwd": repo,
                          "tool_name": name, "tool_input": dict(inputs, **{key: path}),
                          "tool_use_id": call_id,
                          "tool_response": {"content": "observed"},
                          "tool_result": {"text_result_for_llm": "observed"}}, host)


def _prompt(enabled, repo, sid, text, host=None):
    return call(enabled, {"hook_event_name": "UserPromptSubmit", "session_id": sid,
                          "cwd": repo, "prompt": text}, host)


def _start(enabled, repo, sid, source, host=None, **extra):
    return call(enabled, dict({"hook_event_name": "SessionStart", "source": source,
                               "session_id": sid, "cwd": repo}, **extra), host)


def _stock_for(host, enabled, repo):
    """The learned stock, filed where a session of `host` reads it."""
    from tokeneconomizer.knowledge.stage import Knowledge
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode, Copilot, Pi
    src = LiveContext.build(ClaudeCode(), repo, enabled)
    dst = LiveContext.build(Pi() if host == "pi" else Copilot(), repo, enabled)
    Knowledge.load(src.repo.label, src.mech_dir).save(dst.mech_dir)
    return dst


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


def test_card_has_its_own_budget_even_when_native_facts_fill_theirs(tmp_path, env, repo, monkeypatch):
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    store = store_for(enabled, repo)
    store.write("injection.json", {"rendered": "# native\n- A\n- B\n- C\n- D\n"})
    both = dict(enabled, TE_MICROSKILLS="envfacts")
    call(both, {"hook_event_name": "SessionStart", "source": "startup", "session_id": "budget", "cwd": repo})
    assert CLAIM in json.dumps(_read(both, repo, "budget", str(Path(repo) / "source.txt")))


@pytest.mark.parametrize("host,tool", [("pi", "read"), ("copilot", "view")])
def test_knowledge_never_arrives_at_a_start_and_the_read_still_delivers(
        tmp_path, env, repo, monkeypatch, host, tool):
    """Criterion 1 (#333): the startup delivery and `knowledge_startup_share` are gone. No start
    -- fresh, resumed, cleared or compacted -- gives a card, and the session's whole allowance is
    available to what it reads."""
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    dst = _stock_for(host, enabled, repo)
    for source in ("startup", "resume", "clear", "compact"):
        assert CLAIM not in json.dumps(_start(enabled, repo, "s1", source, host))
    assert [e for e in dst.store.read_lines("events.jsonl") if e["kind"] == "knowledge"] == []
    delivered = _read(enabled, repo, "s1", "source.txt", host=host, name=tool, key="path")
    assert CLAIM in json.dumps(delivered)


def test_a_read_delivers_a_card_whose_symbol_lines_the_read_did_not_return(
        tmp_path, env, repo, monkeypatch):
    """Criterion 2 (#333): the read trigger matches the file a read returned, not the lines it
    covered, so a Knowledge about a symbol further down the file still arrives after a partial
    read."""
    pytest.importorskip("tree_sitter_language_pack")
    source = "def alpha():\n    return 1\n\ndef beta():\n    return 2\n"
    enabled = learn_knowledge(tmp_path, env, repo, monkeypatch, {"source.py": source},
                              [{"id": "alpha-one", "claim": "Alpha returns one",
                                "source": "source.py", "symbol": "alpha"}])
    dst = _stock_for("pi", enabled, repo)
    out = _read(enabled, repo, "partial", "source.py", host="pi", name="read", key="path",
                call_id="r1", offset=5, limit=1)
    assert "Alpha returns one" in json.dumps(out)
    (entry,) = [e for e in dst.store.read_lines("events.jsonl") if e["kind"] == "knowledge"]
    assert (entry["knowledge_id"], entry["signal"], entry["trigger"]) == (
        "alpha-one", "source.py", "read")


def test_a_card_the_budget_cannot_hold_is_skipped_for_the_next_one(tmp_path):
    """Criterion 2 (#333): a candidate that does not fit the remaining budget is passed over,
    and the ranking goes on to the next one rather than stopping at it."""
    from tests.test_knowledge_workflow import observed_stage, proposal
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit(proposal(id="long-card", claim="Long claim",
                                 injection="x" * 400)) == (True, "admitted")
    assert stage._admit(proposal(id="short-card", claim="Short claim",
                                 injection="short")) == (True, "admitted")
    # The long card is registered first and covers the file too: too big for 40 tokens, so the
    # short one behind it is delivered.
    _text, chosen = stage.selection(read="source.txt", max_facts=4, max_tokens=40)
    assert [card.id for card, _signal in chosen] == ["short-card"]
    _text, chosen = stage.selection(task="look at source.txt", max_facts=4, max_tokens=40)
    assert [card.id for card, _signal in chosen] == ["short-card"]
    # A card already in context is skipped the same way, and the one behind it is considered.
    _text, chosen = stage.selection(read="source.txt", max_facts=4, max_tokens=200,
                                    given=["short-card"])
    assert [card.id for card, _signal in chosen] == ["long-card"]
    # A card whose contract no longer holds is filtered out before the ranking.
    (tmp_path / "source.txt").write_text("changed\n")
    assert stage.selection(read="source.txt", max_facts=4, max_tokens=200) == ("", [])


def test_three_cards_of_five_then_at_most_two_more(tmp_path, env, repo, monkeypatch):
    """Criterion 3 (#333): the session's card ceiling holds across its turns -- five cards at
    most, so three delivered leave two more and no more."""
    names = ["a.txt", "b.txt", "c.txt", "d.txt", "e.txt", "f.txt"]
    enabled = learn_knowledge(tmp_path, env, repo, monkeypatch,
                              dict.fromkeys(names, "observed\n"),
                              [{"id": n[0], "claim": f"card for {n}", "source": n}
                               for n in names])
    enabled.update(TE_KNOWLEDGE_MAX_CARDS="5", TE_KNOWLEDGE_MAX_TOKENS="3000")
    _stock_for("pi", enabled, repo)

    def read(name):
        return f"card for {name}" in json.dumps(
            _read(enabled, repo, "five", name, host="pi", name="read", key="path",
                  call_id=name))
    assert [read(n) for n in names[:3]] == [True] * 3
    assert [read(n) for n in names[3:]] == [True, True, False]


def test_the_token_ceiling_is_a_ceiling_of_its_own(tmp_path, env, repo, monkeypatch):
    """Criterion 3 (#333): a session's token ceiling stops delivery while the card ceiling still
    has room. One card's block is 39 estimated tokens here."""
    names = ["a.txt", "b.txt", "c.txt", "d.txt"]
    enabled = learn_knowledge(tmp_path, env, repo, monkeypatch,
                              dict.fromkeys(names, "observed\n"),
                              [{"id": n[0], "claim": f"card for {n}", "source": n}
                               for n in names])
    enabled.update(TE_KNOWLEDGE_MAX_CARDS="4", TE_KNOWLEDGE_MAX_TOKENS="61")
    dst = _stock_for("pi", enabled, repo)

    def read(name):
        return f"card for {name}" in json.dumps(
            _read(enabled, repo, "tokens", name, host="pi", name="read", key="path",
                  call_id=name))
    assert read("a.txt")
    assert [read(n) for n in names[1:]] == [False] * 3
    state = dst.store.read("sessions/tokens.json")
    assert state["knowledge_given"] == ["a"]


def test_a_resume_keeps_what_the_conversation_still_holds(tmp_path, env, repo, monkeypatch):
    """Criterion 4 (#333): a block the conversation still carries is deduplicated at a resume --
    neither given again nor counted again."""
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    dst = _stock_for("copilot", enabled, repo)
    assert CLAIM in json.dumps(_read(enabled, repo, "r1", "source.txt", host="copilot",
                                    name="view", key="path"))
    state = dst.store.read("sessions/r1.json")
    spent = (list(state["knowledge_given"]), state["knowledge_tokens"])
    assert CLAIM not in json.dumps(_start(enabled, repo, "r1", "resume", "copilot"))
    state = dst.store.read("sessions/r1.json")
    assert (state["knowledge_given"], state["knowledge_tokens"]) == spent
    assert CLAIM not in json.dumps(_read(enabled, repo, "r1", "source.txt", host="copilot",
                                        name="view", key="path"))


def test_a_resume_restores_a_recorded_block_only_while_its_contract_holds(
        tmp_path, env, repo, monkeypatch):
    """Criterion 4 (#333): a host that rebuilt its start context away gets the block it recorded
    back, by id, charged nothing and counted as no new card; a card whose contract broke is not
    restored, and does not give its place back."""
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    dst = _stock_for("copilot", enabled, repo)
    dst.store.write("sessions/legacy.json", {
        "session_id": "legacy", "cwd": repo, "knowledge_given": ["source-observed"],
        "knowledge_tokens": 39, "knowledge_startup": {"cards": ["source-observed"]}})
    assert CLAIM in json.dumps(_start(enabled, repo, "legacy", "resume", "copilot"))
    state = dst.store.read("sessions/legacy.json")
    assert (state["knowledge_given"], state["knowledge_tokens"]) == (["source-observed"], 39)
    # An identical restore is not a new card: nothing was logged, and the card's place is still
    # taken, so a read of its file gives nothing.
    assert [e for e in dst.store.read_lines("events.jsonl") if e["kind"] == "knowledge"] == []
    assert CLAIM not in json.dumps(_read(enabled, repo, "legacy", "source.txt", host="copilot",
                                        name="view", key="path"))
    # The contract no longer holds: nothing is restored, and what the block spent stays spent.
    (Path(repo) / "support.txt").write_text("changed\n")
    assert CLAIM not in json.dumps(_start(enabled, repo, "legacy", "resume", "copilot"))
    state = dst.store.read("sessions/legacy.json")
    assert (state["knowledge_given"], state["knowledge_tokens"]) == (["source-observed"], 39)


def test_a_compaction_deduplicates_what_it_keeps_and_credits_nothing_back(
        tmp_path, env, repo, monkeypatch):
    """Criterion 4 (#333): Pi's compaction leaves the session's budget spent. What the branch
    still carries is deduplicated; a block it dropped is gone, and its place is not given back."""
    names = ["a.txt", "b.txt", "c.txt"]
    enabled = learn_knowledge(tmp_path, env, repo, monkeypatch,
                              dict.fromkeys(names, "observed\n"),
                              [{"id": n[0], "claim": f"card for {n}", "source": n}
                               for n in names])
    enabled.update(TE_KNOWLEDGE_MAX_CARDS="2", TE_KNOWLEDGE_MAX_TOKENS="3000")
    dst = _stock_for("pi", enabled, repo)

    def read(name):
        return f"card for {name}" in json.dumps(
            _read(enabled, repo, "pi1", name, host="pi", name="read", key="path",
                  call_id=name))
    assert [read(n) for n in names] == [True, True, False]     # two cards, the ceiling spent
    state = dst.store.read("sessions/pi1.json")
    assert sorted(state["knowledge_read_blocks"]) == ["a.txt", "b.txt"]
    spent = (list(state["knowledge_given"]), state["knowledge_tokens"])
    # The block the branch kept is deduplicated: nothing is given or spent again.
    assert _start(enabled, repo, "pi1", "compact", "pi",
                  retained_knowledge_reads=["a.txt"]) == {}
    state = dst.store.read("sessions/pi1.json")
    assert (state["knowledge_given"], state["knowledge_tokens"]) == spent
    assert sorted(state["knowledge_read_blocks"]) == ["a.txt"]
    assert not read("a.txt")
    # The blocks it dropped are gone from the conversation, and their place stays spent.
    assert _start(enabled, repo, "pi1", "compact", "pi", retained_knowledge_reads=[]) == {}
    state = dst.store.read("sessions/pi1.json")
    assert state["knowledge_read_blocks"] == {}
    assert (state["knowledge_given"], state["knowledge_tokens"]) == spent
    assert not read("b.txt")      # its id is still the session's: no new card
    assert not read("c.txt")      # and its place was not given back


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
