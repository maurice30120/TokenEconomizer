import json
from pathlib import Path

import pytest

from tokeneconomizer.knowledge.stage import (KNOWLEDGE_MAX_CANDS, Knowledge, KnowledgeCard,
                                            workspace_id)
from tokeneconomizer.plugin.config import load_config
from tests.test_knowledge_pi import SOURCE, capture_read, pi_read, reads_session
from tests.test_live_hooks import call, env, repo, run_session, store_for  # noqa: F401


def test_knowledge_is_independent_and_disabled_by_default(tmp_path):
    assert not load_config(str(tmp_path), env={}).knowledge
    cfg = load_config(str(tmp_path), env={"TE_KNOWLEDGE": "on", "TE_MICROSKILLS": "off"})
    assert cfg.knowledge and cfg.microskills == "off"


SOURCE_CARD = {"id": "source-observed", "claim": "Source is observed",
               "injection": "Source is observed",
               "detector": [{"path": "source.txt"}, {"path": "support.txt"}]}


def _learn_source_knowledge(tmp_path, env, repo, monkeypatch, card=None):
    """Five live sessions that read `source.txt` and `support.txt` and propose one Knowledge."""
    from tokeneconomizer.plugin import sidecall
    source = Path(repo) / "source.txt"
    source.write_text("observed\n")
    other = Path(repo) / "support.txt"
    other.write_text("support\n")
    knowledge = [SOURCE_CARD if card is None else card]
    monkeypatch.setattr(sidecall, "runner_for",
                        lambda *a, **kw: lambda *a: (json.dumps({"knowledge": knowledge}), 0))
    enabled = dict(env, TE_KNOWLEDGE="on", TE_MICROSKILLS="off", TE_LOOPGUARD="off",
                   TE_TOOLPRUNE="off")
    for i in range(5):
        tp = tmp_path / f"hook{i}.jsonl"
        events = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": str(source)}}, {"type": "tool_use", "id": "r2", "name": "Read", "input": {"file_path": str(other)}}, {"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r", "content": "     1→observed"}]}, "toolUseResult": {"type": "text", "file": {"filePath": str(source), "content": "observed\n", "startLine": 1, "numLines": 1, "totalLines": 1}}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r2", "content": "     1→support"}]}, "toolUseResult": {"type": "text", "file": {"filePath": str(other), "content": "support\n", "startLine": 1, "numLines": 1, "totalLines": 1}}},
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

    def read(host=None):
        return "Source is observed" in json.dumps(call(enabled, {
            "hook_event_name": "PostToolUse", "session_id": sid, "cwd": repo,
            "tool_name": "Read", "tool_input": {"file_path": "source.txt"}, "tool_response": {"content": "observed"}}, host))
    start("startup")
    assert read()
    assert not read()
    assert not read()
    start("resume")                       # Claude replays its context: nothing again
    assert not read()
    start("clear")
    assert read()
    assert not read()
    start("compact")
    assert read()
    # Another session is not affected by this one's memory.
    sid = "other-session"
    start("startup")
    assert read()


def test_a_resumed_session_keeps_the_knowledge_it_was_given(tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin.hosts import ClaudeCode
    # Copilot rebuilds a resumed conversation without its start context, but the Knowledge came
    # as tool context, which stays in the history: it is not given again.
    monkeypatch.setattr(ClaudeCode, "keeps_start_context", False)
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)

    def send(event, **kw):
        return json.dumps(call(enabled, dict({"hook_event_name": event, "session_id": "c1", "cwd": repo}, **kw)))
    def read():
        return send("PostToolUse", tool_name="Read", tool_input={"file_path": "source.txt"},
                    tool_response={"content": "observed"})
    send("SessionStart", source="new")
    assert "Source is observed" in read()
    send("SessionStart", source="resume")
    assert "Source is observed" not in read()
    send("SessionStart", source="clear")
    assert "Source is observed" in read()


def test_hook_uses_current_proof_even_when_session_cache_is_warm(tmp_path, env, repo, monkeypatch):
    import threading
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    payload = {"hook_event_name": "PostToolUse", "session_id": "warm", "cwd": repo,
               "tool_name": "Read", "tool_input": {"file_path": "source.txt"},
               "tool_response": {"content": "observed"}}
    assert "Source is observed" in json.dumps(call(enabled, payload))
    (Path(repo) / "support.txt").write_text("changed\n")
    assert "Source is observed" not in json.dumps(call(enabled, dict(payload, session_id="fresh")))
    (Path(repo) / "support.txt").write_text("support\n")
    assert "Source is observed" in json.dumps(call(enabled, dict(payload, session_id="restored")))
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    result = []
    started = threading.Event()
    def invoke():
        started.set()
        result.append(call(enabled, dict(payload, session_id="race")))
    with ctx.store.locked("mechanisms") as acquired:
        assert acquired
        worker = threading.Thread(target=invoke)
        worker.start()
        assert started.wait(2)
        worker.join(0.2)
        assert worker.is_alive()
        stage = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
        stage.facts.clear()
        stage.save(ctx.mech_dir)
    worker.join(5)
    assert not worker.is_alive()
    assert "Source is observed" not in json.dumps(result)


def observed_stage(tmp_path, files, sessions=2, host="claude"):
    """A `Knowledge` that folded `sessions` sessions reading every file of `files` completely
    and passing a test run, so admission has those observations to resolve against."""
    stage = Knowledge("repo")
    stage.workspace, stage.host = tmp_path, host
    for i in range(sessions):
        uses, results = [], []
        for n, (name, content) in enumerate(files.items()):
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(content)
            lines = len(content.splitlines())
            uses.append({"type": "tool_use", "id": f"r{n}", "name": "Read",
                         "input": {"file_path": str(path)}})
            results.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"r{n}", "content": content}]},
                "toolUseResult": {"type": "text", "file": {
                    "filePath": str(path), "content": content, "startLine": 1,
                    "numLines": lines, "totalLines": lines}}})
        uses.append({"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}})
        events = [{"type": "assistant", "message": {"content": uses}}, *results,
                  {"type": "user", "message": {"content": [
                      {"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}}]
        transcript = tmp_path / f"observed{i}.jsonl"
        transcript.write_text("\n".join(map(json.dumps, events)))
        stage.update(transcript, iid=f"s{i}")
    return stage


def proposal(**fields):
    """One proposed Knowledge: four business fields, `detector` a list of references."""
    candidate = {"id": "source-observed", "claim": "Source is observed",
                 "injection": "Source is observed", "detector": [{"path": "source.txt"}]}
    candidate.update(fields)
    return candidate


# ---- criterion 6: four business fields, no lifecycle, available after the fold ------------
def test_an_admitted_knowledge_is_available_in_the_same_run(tmp_path):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit(proposal()) == (True, "admitted")
    card = stage.facts["source-observed"]
    assert (card.id, card.claim, card.injection) == (
        "source-observed", "Source is observed", "Source is observed")
    assert stage.contract_valid(card)
    assert "Source is observed" in stage.render()
    assert [c.id for c, _ in stage.covering("source.txt")] == ["source-observed"]


def test_a_knowledge_persists_only_its_four_business_fields(tmp_path):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit(proposal()) == (True, "admitted")
    stage.save(tmp_path)
    state = json.loads((tmp_path / "knowledge_state" / "repo.json").read_text())
    assert set(state) == {"repo", "now", "opt_tokens", "last_propose", "facts", "forgotten",
                          "window", "raw_cmds"}
    stored = state["facts"]["source-observed"]
    assert set(stored) == {"id", "claim", "injection", "detector", "internal"}
    assert stored["detector"] == [{"kind": "file", "path": "source.txt",
                                   "sha256": stored["detector"][0]["sha256"]}]
    assert stored["internal"] == {"session": "s1", "observed_lines": {}}
    restored = Knowledge.load("repo", tmp_path)
    restored.workspace = tmp_path
    card = restored.facts["source-observed"]
    assert (card.id, card.claim, card.injection) == (
        "source-observed", "Source is observed", "Source is observed")
    assert card.detector == stored["detector"]
    assert restored.contract_valid(card)


def test_the_rendered_card_is_its_injection_alone(tmp_path):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit(proposal(injection="source.txt is the observed input")) == (True, "admitted")
    assert '"source.txt is the observed input"' in stage.render()


def test_a_changed_source_makes_the_card_ineligible_until_restored(tmp_path):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit(proposal()) == (True, "admitted")
    card = stage.facts["source-observed"]
    (tmp_path / "source.txt").write_text("changed\n")
    assert not stage.contract_valid(card)
    assert "Source is observed" not in stage.render()
    assert card.id in stage.facts        # ineligible, never deleted or marked
    (tmp_path / "source.txt").write_text("observed\n")
    assert stage.contract_valid(card)
    assert "Source is observed" in stage.render()


def test_a_forgotten_knowledge_stays_forgotten(tmp_path):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit(proposal()) == (True, "admitted")
    stage.forget("source-observed")
    assert "Source is observed" not in stage.render()
    assert stage._admit(proposal()) == (False, "forgotten")
    assert stage._admit(proposal(id="another-id")) == (True, "admitted")


# ---- criterion 4/5: admission from one source, several, or none --------------------------
def test_one_session_is_enough_to_admit_a_knowledge(tmp_path):
    """Story 2: a single session's observation is sufficient evidence for an atomic claim."""
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"}, sessions=1)
    assert stage._admit(proposal()) == (True, "admitted")


def test_a_single_observed_file_is_admitted(tmp_path):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit(proposal()) == (True, "admitted")
    assert [proof["kind"] for proof in stage.facts["source-observed"].detector] == ["file"]


def test_a_single_observed_symbol_is_admitted(tmp_path):
    pytest.importorskip("tree_sitter_language_pack")
    stage = observed_stage(tmp_path, {"source.py": "def alpha():\n    return 1\n"})
    assert stage._admit(proposal(detector=[{"path": "source.py", "symbol": "alpha"}])) == (
        True, "admitted")
    card = stage.facts["source-observed"]
    assert card.detector[0]["kind"] == "symbol" and card.detector[0]["symbol"] == "alpha"
    assert stage.signals(card) == ["alpha"]


def test_several_sources_may_prove_one_mechanism(tmp_path):
    stage = observed_stage(tmp_path, {"a.txt": "a observed\n", "b.txt": "b observed\n"})
    assert stage._admit(proposal(detector=[{"path": "a.txt"}, {"path": "b.txt"}])) == (
        True, "admitted")
    card = stage.facts["source-observed"]
    assert stage.files(card) == ["a.txt", "b.txt"]
    assert stage.signals(card) == ["a.txt", "b.txt"]
    assert [c.id for c, _ in stage.covering("b.txt")] == ["source-observed"]
    assert "Source is observed" in stage.render("look at b.txt")
    (tmp_path / "b.txt").write_text("changed\n")
    assert "Source is observed" not in stage.render()


def test_a_bare_file_name_resolves_to_the_one_observed_path(tmp_path):
    stage = observed_stage(tmp_path, {"pkg/deep.txt": "observed\n"})
    assert stage._admit(proposal(detector=[{"path": "deep.txt"}])) == (True, "admitted")
    assert stage.facts["source-observed"].detector[0]["path"] == "pkg/deep.txt"


def test_an_ambiguous_bare_file_name_is_refused(tmp_path):
    stage = observed_stage(tmp_path, {"pkg/deep.txt": "observed\n", "lib/deep.txt": "other\n"})
    assert stage._admit(proposal(detector=[{"path": "deep.txt"}])) == (False, "ambiguous-source")
    assert not stage.facts
    # The full path of either one is not ambiguous.
    assert stage._admit(proposal(detector=[{"path": "lib/deep.txt"}])) == (True, "admitted")


def test_a_proposal_without_evidence_is_refused(tmp_path):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit(proposal(detector=[{"path": "missing.txt"}])) == (
        False, "source-not-observed")
    assert not stage.facts


def test_a_stale_observation_is_refused(tmp_path):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    (tmp_path / "source.txt").write_text("changed\n")
    assert stage._admit(proposal()) == (False, "stale-proof")
    assert not stage.facts


def test_an_empty_proposal_list_admits_nothing(tmp_path):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._apply_proposals(None, []) == 0
    assert not stage.facts and stage.outcomes == []


def test_a_proposal_is_proven_once_per_admission(tmp_path, monkeypatch):
    calls = []
    from tokeneconomizer.knowledge import stage as knowledge_stage
    real = knowledge_stage.verify_proof
    monkeypatch.setattr(knowledge_stage, "verify_proof",
                        lambda root, proof: calls.append(proof) or real(root, proof))
    stage = observed_stage(tmp_path, {"a.txt": "a observed\n", "b.txt": "b observed\n"})
    assert stage._admit(proposal(detector=[{"path": "a.txt"}, {"path": "b.txt"}])) == (
        True, "admitted")
    assert len(calls) == 2       # one verification per resolved reference, and no second pass


@pytest.mark.parametrize("candidate", [
    {"id": "k", "claim": "a claim", "detector": [{"path": "source.txt"}]},
    {"id": "k", "claim": "a claim", "injection": "inject", "detector": []},
    {"id": "k", "claim": "a claim", "injection": "inject", "detector": ["source.txt"]},
    {"id": "k", "claim": "a claim", "injection": "inject",
     "detector": [{"path": "source.txt", "role": "source"}]},
    {"id": "", "claim": "a claim", "injection": "inject", "detector": [{"path": "source.txt"}]},
])
def test_a_proposal_without_the_four_fields_is_refused(tmp_path, candidate):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit(candidate) == (False, "invalid-fields")
    assert not stage.facts


def test_a_synthesized_knowledge_is_refused(tmp_path):
    """The retired `dependencies` form carries nothing admission can prove."""
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit({"id": "synthesis", "claim": "combined",
                         "dependencies": ["x", "y"]}) == (False, "invalid-fields")


def test_a_retired_field_is_not_persisted(tmp_path):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit(proposal(flow="a flow", sources=[{"source": "source.txt"}])) == (
        True, "admitted")
    stage.save(tmp_path)
    state = json.loads((tmp_path / "knowledge_state" / "repo.json").read_text())
    assert set(state["facts"]["source-observed"]) == {"id", "claim", "injection", "detector",
                                                     "internal"}


@pytest.mark.parametrize("candidate", [
    {"id": "Alpha One", "claim": "a claim", "injection": "inject",
     "detector": [{"path": "source.txt"}]},
    {"id": "source_observed", "claim": "a claim", "injection": "inject",
     "detector": [{"path": "source.txt"}]},
])
def test_a_non_kebab_id_is_refused(tmp_path, candidate):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit(candidate) == (False, "invalid-id")
    assert not stage.facts


def test_a_duplicate_claim_and_contract_is_refused_whatever_its_id(tmp_path):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit(proposal()) == (True, "admitted")
    assert stage._admit(proposal()) == (False, "duplicate")
    assert stage._admit(proposal(id="another-id")) == (False, "duplicate")
    assert len(stage.facts) == 1


def test_an_id_already_taken_with_other_content_is_refused_without_overwrite(tmp_path):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit(proposal()) == (True, "admitted")
    assert stage._admit(proposal(claim="Another claim", injection="Another claim")) == (
        False, "id-conflict")
    assert stage.facts["source-observed"].claim == "Source is observed"


def test_a_changed_claim_under_a_new_id_is_admitted(tmp_path):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    assert stage._admit(proposal()) == (True, "admitted")
    assert stage._admit(proposal(id="source-other", claim="Another claim",
                                 injection="Another claim")) == (True, "admitted")
    assert sorted(stage.facts) == ["source-observed", "source-other"]


# ---- criterion 5: a partial read proves only what it returned ----------------------------
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
    (tmp_path / "support.txt").write_text("support\n")
    args = {"path": "source.py", "offset": 2, "limit": 1}
    text = pi_read(SOURCE, 2, 1)
    captures = capture_read(tmp_path, args, text)
    stage = Knowledge("repo")
    stage.workspace, stage.host = tmp_path, "pi"
    for i in range(sessions):
        pi, trace = tmp_path / f"pi{i}.jsonl", tmp_path / f"trace{i}.jsonl"
        reads_session(pi, tmp_path, [("r", args, text, False),
                                     ("support", {"path": "support.txt"}, "support\n", False)])
        claude_trace(trace)
        stage.update(trace, iid=f"s{i}", observed_transcript=pi, captures=captures)
    return stage, source


def partial_candidate(**fields):
    symbol = fields.pop("symbol", "alpha")
    reference = {"path": "source.py"}
    if symbol is not None:
        reference["symbol"] = symbol
    candidate = {"id": "alpha-one", "claim": "Alpha returns one",
                 "injection": "Alpha returns one", "detector": [reference]}
    candidate.update(fields)
    return {k: v for k, v in candidate.items() if v is not None}


def test_partial_knowledge_admits_on_the_symbol_its_read_crossed(tmp_path):
    stage, _ = partial_stage(tmp_path)
    assert stage._admit(partial_candidate()) == (True, "admitted")
    card = stage.facts["alpha-one"]
    assert card.detector[0]["kind"] == "symbol" and card.detector[0]["symbol"] == "alpha"
    assert card.spec["internal"]["observed_lines"] == {"source.py": "2-2 of 7"}


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
    stage.runner = lambda prompt, model: (prompts.append(prompt) or '{"knowledge": []}', 0)
    stage._maybe_propose()
    assert "read only in part" in prompts[0]
    assert "observed_lines" in prompts[0]
    assert Knowledge.fixed_instructions() in prompts[0]
    assert "untrusted data" in prompts[0]


def symbol_less_partial_stage(tmp_path, sessions=2):
    """A `Knowledge` fed Pi sessions that each read line 3 of `source.py`: a blank line."""
    source = tmp_path / "source.py"
    source.write_bytes(SOURCE)
    (tmp_path / "support.txt").write_text("support\n")
    args = {"path": "source.py", "offset": 3, "limit": 1}
    text = pi_read(SOURCE, 3, 1)
    captures = capture_read(tmp_path, args, text)
    stage = Knowledge("repo")
    stage.workspace, stage.host = tmp_path, "pi"
    for i in range(sessions):
        pi, trace = tmp_path / f"blank{i}.jsonl", tmp_path / f"blanktrace{i}.jsonl"
        reads_session(pi, tmp_path, [("r", args, text, False),
                                     ("support", {"path": "support.txt"}, "support\n", False)])
        claude_trace(trace)
        stage.update(trace, iid=f"s{i}", observed_transcript=pi, captures=captures)
    return stage, source


def test_a_partial_source_no_symbol_proves_is_not_offered_to_the_proposer(tmp_path):
    stage, _ = symbol_less_partial_stage(tmp_path)
    dg = stage._featurize({}, [])
    # the read crossed no declaration: nothing the proposer could propose survives admission
    assert [s["path"] for s in dg["observed_sources"]] == ["support.txt"]
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
    (root / "support.txt").write_text("support\n")
    args = {"path": "source.py", "offset": 2, "limit": 1}
    text = pi_read(SOURCE, 2, 1)
    captures = capture_read(root, args, text)
    ctx = LiveContext.build(ClaudeCode(), repo, env)
    stage = Knowledge(workspace_id(ctx.repo.label, ctx.repo.root))
    stage.workspace, stage.host = root, "pi"
    for i in range(2):
        pi, trace = tmp_path / f"cli{i}.jsonl", tmp_path / f"clitrace{i}.jsonl"
        reads_session(pi, root, [("r", args, text, False), ("support", {"path": "support.txt"}, "support\n", False)])
        claude_trace(trace)
        stage.update(trace, iid=f"s{i}", observed_transcript=pi, captures=captures)
    assert stage._admit(partial_candidate()) == (True, "admitted")
    stage.save(ctx.mech_dir)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert cli.main(["--host", "claude", "--cwd", repo, "microskills"]) == 0
    out = capsys.readouterr().out
    assert "evidence=source.py session=s1" in out
    assert '"source.py": "2-2 of 7"' in out


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
    files = dict(files, **{"support.txt": "support\n"})
    paths = {}
    for name, content in files.items():
        paths[name] = Path(repo) / name
        paths[name].parent.mkdir(parents=True, exist_ok=True)
        paths[name].write_text(content)
    knowledge = []
    for candidate in candidates:
        entry = dict(candidate)
        reference = {"path": entry.pop("source")}
        if "symbol" in entry:
            reference["symbol"] = entry.pop("symbol")
        entry.setdefault("injection", entry["claim"])
        entry["detector"] = [reference, {"path": "support.txt"}]
        knowledge.append(entry)
    monkeypatch.setattr(sidecall, "runner_for",
                        lambda *a, **kw: lambda *a: (json.dumps({"knowledge": knowledge}), 0))
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


def test_a_read_budget_keeps_the_first_registered_covering_card(tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    enabled = learn_knowledge(tmp_path, env, repo, monkeypatch,
                              {"a.txt": "observed\n", "b.txt": "observed\n"},
                              [{"id": "a", "claim": "first card", "source": "a.txt"},
                               {"id": "b", "claim": "second card", "source": "b.txt"}])
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    stage = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
    assert sorted(stage.facts) == ["a", "b"]
    payload = {"hook_event_name": "PostToolUse", "session_id": "read", "cwd": repo,
               "tool_name": "Read", "tool_input": {"file_path": "support.txt"},
               "tool_response": {"content": "support"}}
    text = json.dumps(call(dict(enabled, TE_KNOWLEDGE_MAX_CARDS="1"), payload))
    assert "first card" in text and "second card" not in text


def test_a_small_budget_keeps_the_stronger_match_then_the_first_registered(
        tmp_path, env, repo, monkeypatch):
    """Story 9: with a budget too small for every match, the strongest match is injected first,
    then the one registered first."""
    body = "observed\n"
    names = ["pkg/deep.txt", "lib/full.txt", "lib/twin.txt", "lib/rare.txt"]
    enabled = learn_knowledge(
        tmp_path, env, repo, monkeypatch, {n: body for n in names},
        [{"id": n.split("/")[1][:4], "claim": f"{n} is observed", "source": n} for n in names])
    one = dict(TE_KNOWLEDGE_MAX_CARDS="1")
    # Registration order puts the file-name match first; the full path is the stronger match.
    assert "lib/full.txt is observed" in prompt(enabled, repo, "b", "read deep.txt and lib/full.txt", **one)
    assert "lib/full.txt is observed" in prompt(enabled, repo, "c", "lib/full.txt then deep.txt", **one)
    # Equal matches: registration order decides.
    both = "lib/twin.txt and lib/rare.txt"
    assert "lib/twin.txt is observed" in prompt(enabled, repo, "d", both, **one)
    # Delivered native facts do not alter the Knowledge limit.
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    ctx.store.write("injection.json", {"rendered": "# native\n- A\n- B\n"})
    together = dict(enabled, TE_MICROSKILLS="envfacts")
    start = {"hook_event_name": "SessionStart", "source": "startup", "session_id": "n", "cwd": repo}
    assert "- B" in json.dumps(call(dict(together, TE_MICROSKILLS_MAX_FACTS="3"), start))
    text = prompt(together, repo, "n", "deep.txt lib/full.txt lib/twin.txt", **one)
    assert text.count("is observed") == 1 and "lib/full.txt is observed" in text


def test_a_symbol_named_in_the_prompt_outranks_a_file_match(tmp_path, env, repo, monkeypatch):
    """A symbol source is a Knowledge Signal on its own: naming it needs no file named."""
    pytest.importorskip("tree_sitter_language_pack")
    code = "def target():\n    return 1\n"
    enabled = learn_knowledge(
        tmp_path, env, repo, monkeypatch, {"first.txt": "observed\n", "second.py": code},
        [{"id": "file", "claim": "first.txt is observed", "source": "first.txt"},
         {"id": "sym", "claim": "target returns one", "source": "second.py", "symbol": "target"}])
    text = prompt(enabled, repo, "a", "in first.txt look at target", TE_KNOWLEDGE_MAX_CARDS="1")
    assert "target returns one" in text and "first.txt is observed" not in text


# ---- criterion 2: one call, one observation pass, two lists, one charge ------------------
DETECTOR = {"scope": "pytest", "confirm": "passed"}


def session_events(repo):
    """One Claude session: it reads source.txt and support.txt and passes a test run."""
    source, support = Path(repo) / "source.txt", Path(repo) / "support.txt"
    content = {"source.txt": "observed\n", "support.txt": "support\n"}
    uses, results = [], []
    for n, path in enumerate((source, support)):
        text = content[path.name]
        uses.append({"type": "tool_use", "id": f"r{n}", "name": "Read",
                     "input": {"file_path": str(path)}})
        results.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"r{n}", "content": text}]},
            "toolUseResult": {"type": "text", "file": {
                "filePath": str(path), "content": text, "startLine": 1,
                "numLines": 1, "totalLines": 1}}})
    uses.append({"type": "tool_use", "id": "sh", "name": "Bash", "input": {"command": "pytest"}})
    return [{"type": "assistant", "message": {"content": uses}}, *results,
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "sh", "content": "passed"}]}}]


def fold_sessions(tmp_path, env, repo, monkeypatch, runner, sessions=3, **settings):
    """Fold `sessions` read-and-test sessions with `runner` as the proposer; returns the calls."""
    from tokeneconomizer.plugin import sidecall
    (Path(repo) / "source.txt").write_text("observed\n")
    (Path(repo) / "support.txt").write_text("support\n")
    calls = []

    def stub(prompt, model):
        calls.append(prompt)
        return runner()
    monkeypatch.setattr(sidecall, "runner_for", lambda *a, **kw: stub)
    enabled = dict(env, TE_LOOPGUARD="off", TE_TOOLPRUNE="off", **settings)
    for i in range(sessions):
        path = tmp_path / f"session{i}.jsonl"
        path.write_text("\n".join(map(json.dumps, session_events(repo))))
        run_session(enabled, repo, f"s{i}", str(path))
    return calls, enabled


def test_both_missions_share_one_call_one_observation_pass_and_one_charge(
        tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.knowledge import stage as knowledge_stage
    from tokeneconomizer.plugin import sidecall  # noqa: F401
    from tokeneconomizer.microskills.distiller import Distiller
    prepared = []
    real = knowledge_stage.observations
    monkeypatch.setattr(knowledge_stage, "observations",
                        lambda *a, **kw: (prepared.append(1) or real(*a, **kw)))
    native = [{"id": f"n{i}", "claim": f"native {i}", "cite": ["s0", "s1"],
               "detector": DETECTOR} for i in range(6)]
    knowledge = [{"id": f"k{i}", "claim": f"knowledge {i}", "injection": f"knowledge {i}",
                  "detector": [{"path": "source.txt"}]} for i in range(7)]
    knowledge += [{"id": "unsupported", "claim": "nowhere works", "injection": "nowhere",
                   "detector": [{"path": "missing.txt"}]},
                  {"id": "over-the-cap", "claim": "dropped by the cap", "injection": "dropped",
                   "detector": [{"path": "source.txt"}]}]
    calls, enabled = fold_sessions(
        tmp_path, env, repo, monkeypatch,
        lambda: (json.dumps({"extractors": [], "facts": native, "knowledge": knowledge}), 5),
        TE_KNOWLEDGE="on", TE_MICROSKILLS="distiller")
    # One proposal call for both missions, and one observation pass per fold.
    assert len(calls) == 1
    assert len(prepared) == 3
    prompt = calls[0]
    assert prompt.count(Knowledge.fixed_instructions()) == 1
    assert "Observed sources" in prompt
    assert "up to 4 facts and up to 8 Knowledge candidates" in prompt
    assert "JSON list of <=4 such objects" in prompt      # the native cap is unchanged
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    rows = list(ctx.store.read_lines("ledger.jsonl"))
    row = next(r for r in rows if (r.get("injection") or {}).get("shared_proposals"))
    # Each mission keeps its own list, cap and validator; the cost is charged once.
    assert row["injection"]["shared_proposals"] == {
        "native": {"proposed": 4, "admitted": 4},
        "knowledge": {"proposed": 8, "admitted": 7, "rejected": {"source-not-observed": 1}},
    }
    assert row["knowledge"]["optimizer_tokens"] == 0.0
    assert row["overhead"]["optimizer_tokens"] == 5
    native_cards = Distiller.load(ctx.repo.label, ctx.mech_dir)
    assert sorted(native_cards.facts) == ["n0", "n1", "n2", "n3"]
    stage = Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
    assert sorted(stage.facts) == [f"k{i}" for i in range(7)]


# ---- criterion 3: fixed instructions, measured with one tokenizer ------------------------
def test_the_knowledge_instructions_fit_inside_the_native_fixed_instructions():
    """Mission, format and constraints, and nothing that varies with the fold, measured with
    the ledger's own estimator against the native mission's fixed instructions."""
    from tokeneconomizer.microskills import distiller
    from tokeneconomizer.pricing import approx_tokens
    instructions = Knowledge.fixed_instructions()
    assert approx_tokens(instructions) <= approx_tokens(distiller.PROPOSER_SYSTEM_GENERIC)
    assert instructions.startswith(
        "Produce knowledge about how the code works that a future session would benefit from "
        "knowing to avoid repeating exploration or reasoning.")
    # Nothing variable rides along: the observations have their own block.
    assert "Observed sources (paths relative to the repository" not in instructions


# ---- criterion 1: which missions a fold runs --------------------------------------------
def trap_events(repo):
    """One session that falls into the environment trap every time: bare `pytest` is missing."""
    events = session_events(repo)
    events[0]["message"]["content"] += [
        {"type": "tool_use", "id": "sh1", "name": "Bash", "input": {"command": "pytest -q"}},
        {"type": "tool_use", "id": "sh2", "name": "Bash",
         "input": {"command": "python -m pytest -q"}}]
    events += [
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "sh1",
             "content": "bash: pytest: command not found", "is_error": True}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "sh2", "content": "1 passed in 0.1s"}]}},
    ]
    return events


def fold_activation(tmp_path, env, repo, monkeypatch, microskills, knowledge, sessions=3):
    """Fold `sessions` trap sessions under one activation cell; returns (calls, store, ledger)."""
    import glob
    import os
    from tokeneconomizer.plugin import sidecall
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    (Path(repo) / "source.txt").write_text("observed\n")
    (Path(repo) / "support.txt").write_text("support\n")
    native = [{"id": "native", "claim": "native claim", "cite": ["s0", "s1"],
               "detector": DETECTOR}]
    card = {"id": "source-observed", "claim": "Source is observed",
            "injection": "Source is observed", "detector": [{"path": "source.txt"}]}
    calls = []

    def stub(prompt, model):
        calls.append(prompt)
        return json.dumps({"extractors": [], "facts": native, "knowledge": [card]}), 5
    monkeypatch.setattr(sidecall, "runner_for", lambda *a, **kw: stub)
    enabled = dict(env, TE_LOOPGUARD="off", TE_TOOLPRUNE="off",
                   TE_MICROSKILLS=microskills, TE_KNOWLEDGE=knowledge)
    for i in range(sessions):
        path = tmp_path / f"cell{i}.jsonl"
        path.write_text("\n".join(map(json.dumps, trap_events(repo))))
        run_session(enabled, repo, f"s{i}", str(path))
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    state = glob.glob(os.path.join(ctx.mech_dir, "knowledge_state", "*.json"))
    rows = list(ctx.store.read_lines("ledger.jsonl"))
    return {"calls": calls, "rows": rows, "ctx": ctx, "knowledge_state": state,
            "injection": ctx.store.read("injection.json") or {}}


@pytest.mark.parametrize("microskills,knowledge,calls", [
    ("off", "off", 0),
    ("envfacts", "off", 0),
    ("envfacts+distiller", "off", 1),
    ("off", "on", 1),
    ("envfacts", "on", 1),
    ("envfacts+distiller", "on", 1),
])
def test_the_activation_matrix_decides_which_missions_run(
        tmp_path, env, repo, monkeypatch, microskills, knowledge, calls):
    """Every cell of the activation matrix: which missions call a model, which write state, and
    what the free `envfacts` layer still does -- unchanged in all six cells."""
    import glob
    import os
    from tokeneconomizer.microskills.distiller import Distiller
    fold = fold_activation(tmp_path, env, repo, monkeypatch, microskills, knowledge)
    ctx = fold["ctx"]
    assert len(fold["calls"]) == calls and fold["rows"]
    # The free layer learns wherever it is on, and nowhere else.
    envfacts = glob.glob(os.path.join(ctx.mech_dir, "envfacts_state", "*.json"))
    assert bool(envfacts) == ("envfacts" in microskills)
    if envfacts:
        assert "form_repair:run_tests:pytest" in json.loads(Path(envfacts[0]).read_text())["facts"]
    if microskills != "off":
        assert fold["injection"]["profile"] == microskills
    # The paid native mission runs exactly where the profile pays for it.
    paid_native = "distiller" in microskills
    assert ("native" in Distiller.load(ctx.repo.label, ctx.mech_dir).facts) == paid_native
    # The Knowledge mission runs, and writes state, exactly where it is on.
    assert bool(fold["knowledge_state"]) == (knowledge == "on")
    stage = (Knowledge.load(workspace_id(ctx.repo.label, repo), ctx.mech_dir)
             if fold["knowledge_state"] else None)
    assert (stage is not None and "source-observed" in stage.facts) == (knowledge == "on")
    if not calls:
        assert all(row["overhead"]["optimizer_tokens"] == 0 for row in fold["rows"])
        return
    # The fold that ticked is the one whose work cost something.
    row = max(fold["rows"], key=lambda r: r["overhead"]["optimizer_tokens"])
    injection = row["injection"] or {}
    if microskills != "off":
        # No `envfacts` path starts a paid micro-skills mission: its layer learns for free.
        assert injection["optimizer_tokens"] == (5 if paid_native else 0)
    if knowledge == "on":
        # One charge for the fold: Knowledge's own call, or the shared one on the native stage.
        assert row["overhead"]["optimizer_tokens"] == 5
        assert (row["knowledge"] or {})["optimizer_tokens"] == (0.0 if paid_native else 5.0)


@pytest.mark.parametrize("propose_every,sessions,calls", [(2, 4, 2), (3, 4, 1)])
def test_knowledge_proposes_on_the_native_cadence(
        tmp_path, env, repo, monkeypatch, propose_every, sessions, calls):
    card = {"id": "source-observed", "claim": "Source is observed",
            "injection": "Source is observed", "detector": [{"path": "source.txt"}]}
    made, _enabled = fold_sessions(
        tmp_path, env, repo, monkeypatch,
        lambda: (json.dumps({"knowledge": [card]}), 0), sessions=sessions,
        TE_KNOWLEDGE="on", TE_MICROSKILLS="off",
        TE_MICROSKILLS_PROPOSE_EVERY=str(propose_every))
    assert len(made) == calls




# ---- criterion 7: admissions and refusals logged locally, per memory type ----------------
def test_admissions_and_rejections_are_logged_with_their_reason(tmp_path, env, repo, monkeypatch):
    knowledge = [{"id": "source-observed", "claim": "Source is observed",
                  "injection": "Source is observed", "detector": [{"path": "source.txt"}]},
                 {"id": "unsupported", "claim": "Nowhere works", "injection": "nowhere",
                  "detector": [{"path": "missing.txt"}]},
                 {"id": "incomplete", "claim": "No contract", "injection": "no contract",
                  "detector": []}]
    _calls, enabled = fold_sessions(
        tmp_path, env, repo, monkeypatch,
        lambda: (json.dumps({"knowledge": knowledge}), 0),
        TE_KNOWLEDGE="on", TE_MICROSKILLS="off")
    log = [line for line in store_for(enabled, repo).read_lines("knowledge_log.jsonl")
           if line["type"] == "knowledge"]
    assert [(line["id"], line["outcome"], line["reason"]) for line in log] == [
        ("source-observed", "admitted", "admitted"),
        ("unsupported", "rejected", "source-not-observed"),
        ("incomplete", "rejected", "invalid-fields"),
    ]
    assert {line["session_id"] for line in log} == {"s1"}
    assert {line["repo"] for line in log} == {"acme/widget"}


def test_a_logging_failure_does_not_fail_the_fold(tmp_path, env, repo, monkeypatch):
    from tokeneconomizer.plugin.store import Store
    real = Store.append
    def append(self, name, record):
        if name == "knowledge_log.jsonl":
            raise OSError("store unavailable")
        return real(self, name, record)
    monkeypatch.setattr(Store, "append", append)
    card = {"id": "source-observed", "claim": "Source is observed",
            "injection": "Source is observed", "detector": [{"path": "source.txt"}]}
    _calls, enabled = fold_sessions(
        tmp_path, env, repo, monkeypatch,
        lambda: (json.dumps({"knowledge": [card]}), 0),
        TE_KNOWLEDGE="on", TE_MICROSKILLS="off")
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    rows = list(ctx.store.read_lines("ledger.jsonl"))
    assert rows and "error" not in (rows[-1].get("knowledge") or {})
    assert "source-observed" in Knowledge.load(
        workspace_id(ctx.repo.label, repo), ctx.mech_dir).facts


def test_the_shared_call_logs_the_proposals_it_admits(tmp_path, env, repo, monkeypatch):
    """With both missions active the Knowledge proposals come back on the native tick: their
    outcomes are logged there, refusals with the reason that refused them."""
    native = [{"id": "native", "claim": "native claim", "cite": ["s0", "s1"],
               "detector": DETECTOR}]
    knowledge = [{"id": f"k{i}", "claim": f"knowledge {i}", "injection": f"knowledge {i}",
                  "detector": [{"path": "source.txt"}]} for i in range(7)]
    knowledge.append({"id": "unsupported", "claim": "Nowhere works", "injection": "nowhere",
                      "detector": [{"path": "missing.txt"}]})
    _calls, enabled = fold_sessions(
        tmp_path, env, repo, monkeypatch,
        lambda: (json.dumps({"extractors": [], "facts": native, "knowledge": knowledge}), 5),
        TE_KNOWLEDGE="on", TE_MICROSKILLS="distiller")
    log = [line for line in store_for(enabled, repo).read_lines("knowledge_log.jsonl")
           if line["type"] == "knowledge"]
    refused = next(line for line in log if line["id"] == "unsupported")
    assert (refused["outcome"], refused["reason"], refused["session_id"], refused["host"],
            refused["repo"]) == ("rejected", "source-not-observed", "s1", "claude",
                                 "acme/widget")
    assert [line["id"] for line in log if line["outcome"] == "admitted"] == [
        f"k{i}" for i in range(7)]


# ---- criteria 4/5: the refusal and fallback cases the four-field card keeps ---------------
@pytest.mark.parametrize("parser_available", [True, False])
def test_a_symbol_requested_in_the_session_survives_unrelated_edits_and_fails_closed(
        tmp_path, monkeypatch, parser_available):
    if not parser_available:
        import tree_sitter_language_pack
        def unavailable(*args):
            raise LookupError("unavailable")
        monkeypatch.setattr(tree_sitter_language_pack, "get_parser", unavailable)
    content = "def target():\n    return 1\n\ndef other():\n    return 2\n"
    stage = observed_stage(tmp_path, {"source.py": content}, sessions=1)
    assert stage._admit(proposal(detector=[{"path": "source.py", "symbol": "target"}])) == (
        True, "admitted")
    card = stage.facts["source-observed"]
    assert card.detector[0]["kind"] == ("symbol" if parser_available else "file")
    if not parser_available:
        # A complete read keeps its file proof and records why the symbol is not in it.
        assert card.detector[0]["fallback"] == {"symbol": "target",
                                                "reason": "symbol-unresolvable"}
    assert stage.signals(card) == (["target"] if parser_available else ["source.py"])
    assert "Source is observed" in stage.render()
    # A change to another declaration leaves a symbol contract alone; a file contract sees it.
    (tmp_path / "source.py").write_text(content.replace("return 2", "return 3"))
    assert ("Source is observed" in stage.render()) == parser_available
    # The declaration itself changed: the card is ineligible until the code comes back.
    (tmp_path / "source.py").write_text(content.replace("return 1", "return 4"))
    assert not stage.render()


def test_two_symbols_in_distinct_files_are_admitted(tmp_path):
    pytest.importorskip("tree_sitter_language_pack")
    stage = observed_stage(tmp_path, {"a.py": "def alpha():\n    return 1\n",
                                      "b.py": "def beta():\n    return 2\n"})
    assert stage._admit(proposal(detector=[{"path": "a.py", "symbol": "alpha"},
                                           {"path": "b.py", "symbol": "beta"}])) == (
        True, "admitted")
    card = stage.facts["source-observed"]
    assert [(proof["path"], proof["symbol"]) for proof in card.detector] == [
        ("a.py", "alpha"), ("b.py", "beta")]
    assert stage.signals(card) == ["alpha", "beta"]


@pytest.mark.parametrize("reference", ["uncovered.txt", "./uncovered.txt",
                                       "It calls uncovered.txt.", r"dir\uncovered.txt",
                                       ".github/workflows/test.yml", "dir/my.file.ts"])
def test_a_file_named_in_the_map_must_be_covered_by_the_contract(tmp_path, reference):
    stage = observed_stage(tmp_path, {"source.txt": "observed\n"})
    for name in ("uncovered.txt", "dir/uncovered.txt", ".github/workflows/test.yml",
                 "dir/my.file.ts"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n")
    assert stage._admit(proposal(injection="source.txt calls " + reference)) == (
        False, "uncovered-file")
    assert not stage.facts


@pytest.mark.parametrize("failure", ["empty_window", "context_error", "admission_error"])
def test_a_native_proposal_survives_an_unusable_knowledge_context(
        tmp_path, env, repo, monkeypatch, failure):
    """Knowledge is the optional half of the shared call: when its context or its admission
    fails, the native tick still runs, still answers and is still charged once."""
    from tokeneconomizer.microskills.distiller import Distiller
    native = [{"id": "native", "claim": "native claim", "cite": ["s0", "s1"],
               "detector": DETECTOR}]
    card = {"id": "source-observed", "claim": "Source is observed",
            "injection": "Source is observed", "detector": [{"path": "source.txt"}]}
    if failure == "empty_window":
        monkeypatch.setattr(Knowledge, "update", lambda *a, **kw: None)
    else:
        def fail(*args):
            raise ValueError("invalid Knowledge context")
        monkeypatch.setattr(Knowledge,
                            "fixed_instructions" if failure == "context_error"
                            else "_apply_proposals", fail)
    calls, enabled = fold_sessions(
        tmp_path, env, repo, monkeypatch,
        lambda: (json.dumps({"extractors": [], "facts": native, "knowledge": [card]}), 5),
        TE_KNOWLEDGE="on", TE_MICROSKILLS="distiller")
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    ctx = LiveContext.build(ClaudeCode(), repo, enabled)
    assert "native" in Distiller.load(ctx.repo.label, ctx.mech_dir).facts
    assert len(calls) == 1
    row = max(ctx.store.read_lines("ledger.jsonl"),
              key=lambda r: r["overhead"]["optimizer_tokens"])
    assert row["overhead"]["optimizer_tokens"] == 5
    if failure == "admission_error":
        assert row["injection"]["shared_proposals"]["knowledge"]["error"] == "proposal not saved"
    else:
        assert "shared_proposals" not in row["injection"]
