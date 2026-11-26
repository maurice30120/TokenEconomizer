"""The prompt trigger on Pi, and the campaign's A/B/C/D selectors (#334).

The selector is temporary: spec #329's measurement campaign runs the four arms, and #336
removes it once it has decided. What is not temporary is the prompt path itself -- it reuses
the post-read budget, dedup and logging -- and criterion 4's rule that a card costs the same
however it arrived, including across a Pi compaction.
"""
import json
from pathlib import Path

import pytest

from tokeneconomizer.knowledge.stage import Knowledge
from tests.test_knowledge_index import FakeEmbedder
from tests.test_knowledge_read import _prompt, _read, _start, _stock_for
from tests.test_knowledge_workflow import _learn_source_knowledge
from tests.test_live_hooks import call, env, repo, store_for  # noqa: F401

CLAIM = "Source is observed"


def variant(enabled, name):
    """The same session's settings, under one of the campaign's selectors."""
    return dict(enabled, TE_KNOWLEDGE_VARIANT=name)


def test_the_selector_is_a_setting_of_four_values_and_defaults_to_both_triggers(tmp_path):
    """Criterion 3 (#334): one setting chooses the arm, and a value it does not know leaves the
    session on the default rather than on an arm nobody chose."""
    from tokeneconomizer.plugin.config import load_config
    assert load_config(str(tmp_path), env={}).knowledge_triggers == ("prompt", "read")
    for name, triggers in (("a", ("prompt",)), ("b", ("read",)),
                           ("c", ("prompt", "read")), ("d", ())):
        cfg = load_config(str(tmp_path), env={"TE_KNOWLEDGE_VARIANT": name})
        assert (cfg.knowledge_variant, cfg.knowledge_triggers) == (name, triggers)
    unknown = load_config(str(tmp_path), env={"TE_KNOWLEDGE_VARIANT": "e"})
    assert unknown.knowledge_variant == "c" and unknown.warnings


def test_a_pi_prompt_answer_keeps_its_message_apart_from_its_section():
    """Criterion 1 (#334): the first prompt of a session can carry the repository map through
    Pi's section and a card as a message. The two channels stay separate, which is what leaves
    the system prompt -- and the cached prefix -- untouched by a card."""
    from tokeneconomizer.plugin.hosts import Pi, merge_outputs
    merged = merge_outputs(Pi().context("UserPromptSubmit", "map"),
                           Pi().prompt_message("UserPromptSubmit", "card"))
    assert merged["hookSpecificOutput"] == {"hookEventName": "UserPromptSubmit",
                                            "additionalContext": "map",
                                            "promptMessage": "card"}


def test_pi_gets_the_knowledge_a_prompt_names_as_a_message_after_the_prompt(
        tmp_path, env, repo, monkeypatch):
    """Criterion 1 (#334): on Pi the prompt trigger arrives through `promptMessage`, which the
    extension sends as a message after the user's prompt. Its `additionalContext` -- the channel
    it writes the `tokeneconomizer` system-prompt section from -- stays empty, so the cached
    prefix is what it was."""
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    _stock_for("pi", enabled, repo)
    assert _prompt(enabled, repo, "p1", "rename the widget", host="pi") == {}
    out = _prompt(enabled, repo, "p1", "check source.txt", host="pi")
    assert out["hookSpecificOutput"].keys() == {"hookEventName", "promptMessage"}
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert CLAIM in out["hookSpecificOutput"]["promptMessage"]
    entry = [e for e in store_for(enabled, repo, host="pi").read_lines("events.jsonl")
             if e["kind"] == "knowledge"][-1]
    assert (entry["knowledge_id"], entry["trigger"], entry["signal"]) == (
        "source-observed", "prompt", "source.txt")


def test_the_prompt_and_the_read_share_one_ledger_and_one_dedup(tmp_path, env, repo, monkeypatch):
    """Criterion 1 (#334): the prompt path reuses `_inject_knowledge`, so a card it gave is not
    given again by a read, and the session's `knowledge_given`/`knowledge_tokens` are the only
    accounting there is."""
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    _stock_for("pi", enabled, repo)
    store = store_for(enabled, repo, host="pi")
    assert CLAIM in json.dumps(_prompt(enabled, repo, "s1", "check source.txt", host="pi"))
    state = store.read("sessions/s1.json")
    spent = (state["knowledge_given"], state["knowledge_tokens"])
    assert spent[0] == ["source-observed"] and spent[1] > 0
    assert CLAIM not in json.dumps(_read(enabled, repo, "s1", "source.txt", host="pi",
                                         name="read", key="path", call_id="r1"))
    assert (store.read("sessions/s1.json")["knowledge_given"],
            store.read("sessions/s1.json")["knowledge_tokens"]) == spent


@pytest.mark.parametrize("name,prompt_gives,read_gives",
                         [("a", True, False), ("b", False, True), ("c", True, True),
                          ("d", False, False)])
def test_a_selector_runs_only_its_own_triggers(
        tmp_path, env, repo, monkeypatch, name, prompt_gives, read_gives):
    """Criterion 3 (#334): A runs the prompt trigger alone, B the read trigger alone, C both and
    D neither, on one Pi environment."""
    enabled = variant(_learn_source_knowledge(tmp_path, env, repo, monkeypatch), name)
    _stock_for("pi", enabled, repo)
    prompted = CLAIM in json.dumps(_prompt(enabled, repo, "pr", "check source.txt", host="pi"))
    read = CLAIM in json.dumps(_read(enabled, repo, "re", "source.txt", host="pi", name="read",
                                     key="path", call_id="r1"))
    assert (prompted, read) == (prompt_gives, read_gives)


def test_every_arm_spends_one_global_ceiling_between_its_triggers(tmp_path, env, repo, monkeypatch):
    """Criterion 3 (#334): the arms differ in which triggers run, not in what they may spend. One
    `knowledge_max_cards` bounds both, so a card the prompt delivered leaves the read nothing --
    and the read then searches nothing at all."""
    from tests.test_knowledge_workflow import learn_knowledge
    names = ["a.txt", "b.txt"]
    enabled = learn_knowledge(tmp_path, env, repo, monkeypatch,
                              dict.fromkeys(names, "observed\n"),
                              [{"id": n[0], "claim": f"card for {n}", "source": n}
                               for n in names])
    enabled.update(TE_KNOWLEDGE_MAX_CARDS="1", TE_KNOWLEDGE_MAX_TOKENS="3000")
    _stock_for("pi", enabled, repo)
    block = json.dumps(_prompt(enabled, repo, "c1", "check a.txt and b.txt", host="pi"))
    assert ("card for a.txt" in block) != ("card for b.txt" in block)
    assert "card for" not in json.dumps(_read(enabled, repo, "c1", "b.txt", host="pi",
                                              name="read", key="path", call_id="r1"))


def test_variant_d_gives_no_knowledge_at_all_and_leaves_the_native_facts_alone(
        tmp_path, env, repo, monkeypatch):
    """Criterion 3 (#334): D is the control arm: no Knowledge from any trigger, while the
    micro-skills stay native."""
    enabled = variant(_learn_source_knowledge(tmp_path, env, repo, monkeypatch), "d")
    _stock_for("pi", enabled, repo)
    store = store_for(enabled, repo, host="pi")
    both = dict(enabled, TE_MICROSKILLS="envfacts")
    store.write("injection.json", {"rendered": "# native\n- native fact\n"})
    started = _start(both, repo, "d1", "startup", "pi")
    assert "native fact" in json.dumps(started)
    assert CLAIM not in json.dumps(started)
    assert CLAIM not in json.dumps(_prompt(both, repo, "d1", "check source.txt", host="pi"))
    assert CLAIM not in json.dumps(_read(both, repo, "d1", "source.txt", host="pi", name="read",
                                        key="path", call_id="r1"))
    assert [e for e in store.read_lines("events.jsonl") if e["kind"] == "knowledge"] == []


def test_a_budget_spent_before_the_prompt_ranks_nothing(tmp_path, env, repo, monkeypatch):
    """Criterion 1 (#334): the budget is read before any embedding work. With the conversation's
    allowance spent, the prompt searches nothing -- no card is ranked, no vector is computed, and
    no index is written."""
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    _stock_for("pi", enabled, repo)
    store = store_for(enabled, repo, host="pi")
    store.write("sessions/spent.json", {
        "session_id": "spent", "host": "pi", "cwd": repo,
        "knowledge_given": ["source-observed"], "knowledge_tokens": 300})
    embedder = FakeEmbedder()
    monkeypatch.setattr(Knowledge, "embedder", embedder)
    assert _prompt(enabled, repo, "spent", "check source.txt", host="pi") == {}
    assert embedder.batches == []
    assert not Path(store.path("mechanisms", "knowledge_index")).exists()


def test_a_compaction_charges_a_prompted_card_and_a_read_card_the_same(
        tmp_path, env, repo, monkeypatch):
    """Criterion 4 (#334): a card costs the same however it arrived. Pi's compaction is not a
    fresh start, so both triggers keep the ids and the charge spent -- nothing is refunded, and
    nothing records which read delivered what any more."""
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    _stock_for("pi", enabled, repo)
    store = store_for(enabled, repo, host="pi")
    assert CLAIM in json.dumps(_prompt(enabled, repo, "p", "check source.txt", host="pi"))
    assert CLAIM in json.dumps(_read(enabled, repo, "r", "source.txt", host="pi", name="read",
                                     key="path", call_id="call-1"))
    spent = {sid: (list(store.read(f"sessions/{sid}.json")["knowledge_given"]),
                   store.read(f"sessions/{sid}.json")["knowledge_tokens"]) for sid in ("p", "r")}
    for sid in ("p", "r"):
        assert _start(enabled, repo, sid, "compact", "pi") == {}
        state = store.read(f"sessions/{sid}.json")
        assert (state["knowledge_given"], state["knowledge_tokens"]) == spent[sid]
        # Nothing records the read block the compaction dropped: no refund exists to need it.
        assert "knowledge_read_blocks" not in state
    # Neither card is given again: the charge is still the conversation's.
    assert CLAIM not in json.dumps(_prompt(enabled, repo, "p", "check source.txt", host="pi"))
    assert CLAIM not in json.dumps(_read(enabled, repo, "r", "source.txt", host="pi", name="read",
                                         key="path", call_id="call-2"))
