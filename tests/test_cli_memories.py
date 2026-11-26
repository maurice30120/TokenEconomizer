"""`te microskills`: the two memories a repository has, in one list.

The listing is one pass over both stocks -- micro-skills first, then Knowledge, each row saying
which memory it belongs to, with every claim, the Knowledge contracts verified against the
checkout as they are now, and the forgotten entries of both. `--type` narrows the listing, and
`forget`/`unforget` to one memory; an id both memories hold is refused, with nothing changed,
because which one to stop is the person's to say.
"""
import glob
import json
import os

import pytest

from tokeneconomizer.knowledge.stage import Knowledge
from tokeneconomizer.plugin import cli

from tests.test_knowledge_workflow import _learn_source_knowledge, read_source_transcript
from tests.test_live_hooks import (call, env, repo, run_session, store_for,  # noqa: F401
                                   trap_session)

NATIVE_ID = "form_repair:run_tests:pytest"
KNOWLEDGE_ID = "source-observed"
NATIVE_CLAIM = "`pytest …` fails here with command not found; `python -m pytest …` works."
KNOWLEDGE_CLAIM = "Source is observed"


@pytest.fixture
def both(env, repo, tmp_path, monkeypatch):  # noqa: F811
    """A repository whose two memories both hold something: one Knowledge from five sessions
    that read `source.txt`, one native fact from six sessions that fell into the `pytest` trap."""
    _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    for i in range(6):
        run_session(env, repo, f"n{i}", trap_session(str(tmp_path / f"n{i}.jsonl"), repo, i))
    return env


@pytest.fixture
def te(env, repo, monkeypatch, capsys):  # noqa: F811
    """`te --host claude --cwd REPO ...` in the hooks' environment: (exit code, output)."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    def run(*argv):
        capsys.readouterr()
        code = cli.main(["--host", "claude", "--cwd", repo, *argv])
        return code, capsys.readouterr().out
    return run


def rows(out, memory):
    """The listing rows of one memory, in the order printed."""
    return [line for line in out.splitlines() if line.strip().startswith(memory + " ")]


def row(out, text):
    (found,) = [line for line in out.splitlines() if line.strip().startswith(
        ("microskills ", "knowledge ")) and text in line]
    return found


def stock(env, repo):  # noqa: F811
    """(native, knowledge): the two state files, in the store's own layout."""
    store = store_for(env, repo)
    (native,) = glob.glob(store.path("mechanisms", "envfacts_state", "*.json"))
    (knowledge,) = glob.glob(store.path("mechanisms", "knowledge_state", "*.json"))
    return native, knowledge


def share_the_id(env, repo, fid=NATIVE_ID):  # noqa: F811
    """File the Knowledge under the native fact's own id: one id in both memories, which is what
    `forget` has to refuse rather than resolve to the first layer."""
    mechanisms = store_for(env, repo).path("mechanisms")
    stage = Knowledge.load("acme/widget", mechanisms)
    stage.workspace = repo
    card = stage.facts.pop(KNOWLEDGE_ID)
    card.id = card.spec["id"] = fid
    stage.facts[fid] = card
    stage.save(mechanisms)


# ---- #332/2: one list over two memories ---------------------------------------------------
def test_the_listing_shows_the_micro_skills_then_the_knowledge(both, te):
    code, out = te("microskills")
    assert code == 0
    assert NATIVE_CLAIM in out                    # the block the next session receives
    native, knowledge = row(out, NATIVE_ID), row(out, KNOWLEDGE_ID)
    assert native.split()[0] == "microskills"
    assert knowledge.split()[0] == "knowledge"
    assert out.index(native) < out.index(knowledge)
    assert "proof=valid" in knowledge and KNOWLEDGE_CLAIM in knowledge
    assert "evidence=source.txt session=" in out
    assert not any("forgotten" in line for line in (native, knowledge))


def test_the_listing_verifies_each_knowledge_contract_as_the_code_stands_now(both, repo, te):
    assert "proof=valid" in row(te("microskills")[1], KNOWLEDGE_ID)
    with open(os.path.join(repo, "source.txt"), "w") as fh:
        fh.write("changed\n")
    code, out = te("microskills")
    assert code == 0
    changed = row(out, KNOWLEDGE_ID)
    assert "proof=invalid" in changed and KNOWLEDGE_CLAIM in changed


def test_a_micro_skills_only_listing_checks_no_knowledge_contract(both, monkeypatch, te):
    """Criterion: a listing limited to micro-skills verifies no Knowledge contract. Observed by
    patching both Knowledge entry points the listing would have to use -- the stock read and the
    contract check -- and asserting neither is called, then that the same call without the filter
    does call them, so the observation is not vacuous."""
    calls = []
    loaded = Knowledge.load.__func__
    monkeypatch.setattr(Knowledge, "load", classmethod(
        lambda cls, *a, **kw: calls.append("load") or loaded(cls, *a, **kw)))
    monkeypatch.setattr(Knowledge, "contract_valid",
                        lambda self, card: calls.append(card.id) or True)
    code, out = te("microskills", "--type", "microskills")
    assert code == 0
    assert calls == []
    assert NATIVE_CLAIM in out and NATIVE_ID in out
    assert "knowledge symbol grammars" not in out and not rows(out, "knowledge")

    assert te("microskills")[0] == 0
    assert "load" in calls and KNOWLEDGE_ID in calls


def test_a_knowledge_only_listing_shows_the_knowledge_and_nothing_of_the_micro_skills(
        both, te):
    code, out = te("microskills", "--type", "knowledge")
    assert code == 0
    assert not rows(out, "microskills")
    assert NATIVE_CLAIM not in out and NATIVE_ID not in out
    assert KNOWLEDGE_ID in row(out, KNOWLEDGE_ID)


def test_the_listing_shows_the_forgotten_entries_of_both_memories(both, te):
    assert te("microskills", "forget", NATIVE_ID)[0] == 0
    assert te("microskills", "forget", "--type", "knowledge", KNOWLEDGE_ID)[0] == 0
    code, out = te("microskills")
    assert code == 0
    native, knowledge = row(out, NATIVE_ID), row(out, KNOWLEDGE_ID)
    assert native.split()[0] == "microskills" and "forgotten" in native
    assert "command not found" in native
    assert knowledge.split()[0] == "knowledge" and "forgotten" in knowledge
    assert "proof=valid" in knowledge and KNOWLEDGE_CLAIM in knowledge


# ---- #332/3: a shared id is ambiguous, and the filter picks one ---------------------------
def test_a_shared_id_is_refused_without_changing_either_memory(both, env, repo, te):  # noqa: F811
    share_the_id(env, repo)
    native, knowledge = stock(env, repo)
    with open(native) as fh:
        native_before = fh.read()
    with open(knowledge) as fh:
        knowledge_before = fh.read()

    for action in ("forget", "unforget"):
        code, out = te("microskills", action, NATIVE_ID)
        assert code == 1
        assert "not changed" in out and NATIVE_ID in out
        assert "microskills" in out and "knowledge" in out     # both memories are named
        assert "--type" in out                                 # and how to pick one
        assert action in out
        with open(native) as fh:
            assert fh.read() == native_before
        with open(knowledge) as fh:
            assert fh.read() == knowledge_before


def test_the_filter_forgets_only_the_knowledge_holding_the_id(both, env, repo, te):  # noqa: F811
    share_the_id(env, repo)
    native, knowledge = stock(env, repo)
    with open(native) as fh:
        native_before = fh.read()

    code, out = te("microskills", "forget", "--type", "knowledge", NATIVE_ID)
    assert code == 0 and f"forgotten: {NATIVE_ID}" in out
    with open(native) as fh:
        assert fh.read() == native_before                 # the other memory is untouched
    stage = Knowledge.load("acme/widget", store_for(env, repo).path("mechanisms"))
    assert NATIVE_ID in stage.forgotten and NATIVE_ID not in stage.facts

    code, out = te("microskills", "unforget", "--type", "knowledge", NATIVE_ID)
    assert code == 0 and f"brought back: {NATIVE_ID}" in out
    with open(native) as fh:
        assert fh.read() == native_before


def test_the_filter_forgets_only_the_micro_skills_holding_the_id(both, env, repo, te):  # noqa: F811
    share_the_id(env, repo)
    knowledge = stock(env, repo)[1]
    with open(knowledge) as fh:
        knowledge_before = fh.read()

    code, out = te("microskills", "forget", "--type", "microskills", NATIVE_ID)
    assert code == 0 and f"forgotten: {NATIVE_ID}" in out
    with open(knowledge) as fh:
        assert fh.read() == knowledge_before              # the Knowledge is still deliverable
    stage = Knowledge.load("acme/widget", store_for(env, repo).path("mechanisms"))
    assert NATIVE_ID in stage.facts
    code, out = te("microskills", "--type", "knowledge")
    assert NATIVE_ID in row(out, NATIVE_ID) and "proof=valid" in row(out, NATIVE_ID)


def test_a_filtered_forget_does_not_find_an_id_the_other_memory_holds(both, env, repo,  # noqa: F811
                                                                  te):
    """`--type` narrows what `forget` can reach: an id the filtered memory does not hold is
    unknown there, and nothing changes."""
    native, knowledge = stock(env, repo)
    with open(native) as fh:
        native_before = fh.read()
    with open(knowledge) as fh:
        knowledge_before = fh.read()

    code, out = te("microskills", "forget", "--type", "microskills", KNOWLEDGE_ID)
    assert code == 1 and "not changed" in out and KNOWLEDGE_ID in out
    with open(native) as fh:
        assert fh.read() == native_before
    with open(knowledge) as fh:
        assert fh.read() == knowledge_before


# ---- #332/4: what the CLI forgets is not delivered again ---------------------------------
def test_a_forgotten_knowledge_is_never_delivered_and_never_learned_again(
        tmp_path, env, repo, monkeypatch):
    """Criterion 4 at the hooks: a Knowledge forgotten with the CLI stays out of what a session is
    given, and the sessions that keep reading its source do not bring it back."""
    from tokeneconomizer.plugin import cli
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    for key, value in enabled.items():
        monkeypatch.setenv(key, value)
    assert cli.main(["--host", "claude", "--cwd", repo, "microskills",
                     "forget", "--type", "knowledge", "source-observed"]) == 0

    def read(sid):
        return json.dumps(call(enabled, {
            "hook_event_name": "PostToolUse", "session_id": sid, "cwd": repo,
            "tool_name": "Read", "tool_input": {"file_path": "source.txt"},
            "tool_response": {"content": "observed"}}))
    call(enabled, {"hook_event_name": "SessionStart", "session_id": "gone", "cwd": repo,
                   "source": "startup"})
    assert "Source is observed" not in read("gone")

    store = store_for(enabled, repo)
    # The same sources read again, in new sessions: the next proposal comes, and is refused.
    for i in range(3):                   # the proposer runs once every three sessions here
        run_session(enabled, repo, f"again{i}",
                    read_source_transcript(tmp_path / f"again{i}.jsonl", repo))
    assert any(line.get("reason") == "forgotten"
               for line in store.read_lines("knowledge_log.jsonl"))
    assert "source-observed" not in Knowledge.load("acme/widget", store.path("mechanisms")).facts
