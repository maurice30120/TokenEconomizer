"""One repository's Knowledge stock, shared by the checkouts of it on this host.

Spec #329: two clones or worktrees of one repository, on one host, share the Knowledge stock,
and a card's validity is computed against the code of the checkout that reads it. The stock is
still one repository's own, and one memory type's own. The layout change starts it from a blank
four-field stock without touching the other memories or the logs.

The flows run through the plugin's hooks, as a session does, and read the store beside them the
way `te microskills` does.
"""
import json
from pathlib import Path

from tokeneconomizer.knowledge.stage import Knowledge, reset_stock
from tests.test_knowledge_workflow import _learn_source_knowledge, fold_sessions
from tests.test_live_hooks import call, env, repo, run_session, store_for  # noqa: F401

ORIGIN = "https://github.com/acme/widget.git"
CARD = {"id": "source-observed", "claim": "Source is observed",
        "injection": "Source is observed", "detector": [{"path": "source.txt"}]}


def checkout_at(path, origin=ORIGIN):
    """A second checkout of the fixture repository: the same `origin`, its own files."""
    path = Path(path)
    (path / ".git" / "info").mkdir(parents=True)
    (path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (path / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {origin}\n')
    (path / "pyproject.toml").write_text("[project]\nname='w'\n")
    (path / "source.txt").write_text("observed\n")
    (path / "support.txt").write_text("support\n")
    return str(path)


def context_in(enabled, cwd):
    """The plugin's own view of a checkout: its repository, its store, its host."""
    from tokeneconomizer.plugin.context import LiveContext
    from tokeneconomizer.plugin.hosts import ClaudeCode
    return LiveContext.build(ClaudeCode(), cwd, enabled)


def stage_in(enabled, cwd):
    """The stock a checkout reads, its verification rooted in that checkout."""
    ctx = context_in(enabled, cwd)
    stage = Knowledge.load(ctx.repo.label, ctx.mech_dir)
    stage.workspace = cwd
    return stage


def read(enabled, cwd, sid, name, source="new"):
    """One session's start and its read of one file: both hook outputs, as JSON."""
    start = call(enabled, {"hook_event_name": "SessionStart", "source": source,
                           "session_id": sid, "cwd": cwd})
    return json.dumps([start, call(enabled, {
        "hook_event_name": "PostToolUse", "session_id": sid, "cwd": cwd, "tool_name": "Read",
        "tool_input": {"file_path": name}, "tool_response": {"content": "read"}})])


def fold_mixed(tmp_path, env, repo, monkeypatch, cards, sessions=1, **settings):
    """Fold sessions that read both files and fall into the environment trap: the free layer
    learns the environment fact, and the proposer answers `cards`."""
    from tokeneconomizer.plugin import sidecall
    from tests.test_knowledge_workflow import trap_events
    (Path(repo) / "source.txt").write_text("observed\n")
    (Path(repo) / "support.txt").write_text("support\n")
    monkeypatch.setattr(sidecall, "runner_for",
                        lambda *a, **kw: lambda *a: (json.dumps({"knowledge": cards}), 0))
    enabled = dict(env, TE_LOOPGUARD="off", TE_TOOLPRUNE="off", **settings)
    first = len(list(Path(tmp_path).glob("mixed*.jsonl")))     # each call folds new sessions
    for i in range(first, first + sessions):
        path = tmp_path / f"mixed{i}.jsonl"
        path.write_text("\n".join(map(json.dumps, trap_events(repo))))
        run_session(enabled, repo, f"m{i}", str(path))
    return enabled


# ---- criterion 1: one repository, one stock, whichever checkout it is ---------------------
def test_two_clones_of_one_repository_share_the_knowledge_stock(tmp_path, env, repo, monkeypatch):
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    clone = checkout_at(tmp_path / "clone")
    assert "Source is observed" in read(enabled, repo, "here", "support.txt")
    assert "Source is observed" in read(enabled, clone, "there", "support.txt")


def test_a_checkout_without_a_remote_shares_its_stock_with_its_worktree(
        tmp_path, env, repo, monkeypatch):
    """The native fallback: with no `origin`, the repository is its main checkout, which is
    what a linked worktree of it resolves to."""
    from tests.test_live_repos import git_repo, worktree
    main = git_repo(str(tmp_path / "local"))
    enabled = _learn_source_knowledge(tmp_path, env, main, monkeypatch)
    linked = worktree(main, str(tmp_path / "linked"))
    for name in ("source.txt", "support.txt"):
        (Path(linked) / name).write_text((Path(main) / name).read_text())
    assert "Source is observed" in read(enabled, main, "here", "support.txt")
    assert "Source is observed" in read(enabled, linked, "there", "support.txt")


def test_another_repository_of_the_same_name_reads_its_own_stock(
        tmp_path, env, repo, monkeypatch):
    """Sharing follows the repository, not the name it is filed under: another remote's
    `acme/widget` is another repository."""
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    other = checkout_at(tmp_path / "other", "https://gitlab.com/acme/widget.git")
    assert "Source is observed" not in read(enabled, other, "elsewhere", "support.txt")


def test_another_host_reads_its_own_stock(tmp_path, env, repo, monkeypatch):
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    assert list(Path(store_for(enabled, repo).path("mechanisms", "knowledge_state")).iterdir())
    assert not Path(store_for(enabled, repo, host="pi")
                    .path("mechanisms", "knowledge_state")).exists()


def test_the_two_memories_file_their_records_apart(tmp_path, env, repo, monkeypatch):
    """One shared call proposes both lists; each memory type keeps its own."""
    from tokeneconomizer.microskills.distiller import Distiller
    native = [{"id": "native", "claim": "native claim", "cite": ["s0", "s1"],
               "detector": {"scope": "pytest", "confirm": "passed"}}]
    calls, enabled = fold_sessions(
        tmp_path, env, repo, monkeypatch,
        lambda: (json.dumps({"extractors": [], "facts": native, "knowledge": [CARD]}), 5),
        TE_KNOWLEDGE="on", TE_MICROSKILLS="distiller")
    assert len(calls) == 1
    ctx = context_in(enabled, repo)
    assert sorted(Knowledge.load(ctx.repo.label, ctx.mech_dir).facts) == ["source-observed"]
    assert sorted(Distiller.load(ctx.repo.label, ctx.mech_dir).facts) == ["native"]


# ---- criterion 2: validity is the checkout's own -----------------------------------------
def test_a_card_is_valid_against_the_code_of_the_checkout_that_reads_it(
        tmp_path, env, repo, monkeypatch):
    enabled = _learn_source_knowledge(tmp_path, env, repo, monkeypatch)
    clone = checkout_at(tmp_path / "clone")
    (Path(clone) / "support.txt").write_text("diverged\n")
    # The card holds on the code it was learned from, and not on the clone's.
    assert "Source is observed" in read(enabled, repo, "here", "support.txt")
    assert "Source is observed" not in read(enabled, clone, "there", "support.txt")
    # An invalid card stays in the stock, and is usable again once the compatible code is back.
    stage = stage_in(enabled, clone)
    assert "source-observed" in stage.facts
    assert not stage.contract_valid(stage.facts["source-observed"])
    (Path(clone) / "support.txt").write_text("support\n")
    assert "Source is observed" in read(enabled, clone, "after", "support.txt")


# ---- criterion 4: the new format starts from a blank stock -------------------------------
OLD_STOCK = {
    "repo": "acme/widget", "now": 9, "opt_tokens": 0.0, "last_propose": 0,
    "facts": {"old-mechanism": {
        "spec": {"id": "old-mechanism", "claim": "an old mechanism", "flow": "old",
                 "sources": [{"source": "source.txt"}]},
        "life": {"state": "live", "confirm": 2}}},
    "forgotten": {},
    "window": [{"iid": "folded-under-the-old-layout", "edited_files": [], "n_cmds": 0,
                "cmd_templates": [], "test_invocations": []}],
    "raw_cmds": [["old-layout-command", "passed"]]}


def envfacts_state(ctx):
    """The free layer's state file, as the store files it."""
    (path,) = Path(ctx.mech_dir, "envfacts_state").glob("*.json")
    return json.loads(path.read_text())


def test_a_stock_the_layout_cannot_read_is_discarded_and_the_other_memories_stay(
        tmp_path, env, repo, monkeypatch):
    """Criterion 4: the stock starts blank; the micro-skills, the ledger, the log and the folds
    are not the Knowledge stock and stay -- and the sweep does not run a second time."""
    enabled = fold_mixed(tmp_path, env, repo, monkeypatch, [CARD], sessions=1,
                         TE_KNOWLEDGE="off", TE_MICROSKILLS="envfacts")
    ctx = context_in(dict(enabled, TE_KNOWLEDGE="on"), repo)
    stock = Knowledge._path(ctx.mech_dir, ctx.repo.label)
    Path(stock).write_text(json.dumps(OLD_STOCK))
    ctx.store.append("knowledge_log.jsonl", {"at": 0, "type": "knowledge",
                                              "id": "old-mechanism", "outcome": "admitted",
                                              "reason": "admitted"})
    ledger, log = ctx.store.read_lines("ledger.jsonl"), ctx.store.read_lines("knowledge_log.jsonl")
    fold_mixed(tmp_path, env, repo, monkeypatch, [CARD], sessions=1,
               TE_KNOWLEDGE="on", TE_MICROSKILLS="envfacts", TE_MICROSKILLS_PROPOSE_EVERY="1")
    # The stock holds the new card, and nothing of the file the old layout wrote -- neither its
    # cards nor the window and the command history that indexed them.
    state = json.loads(Path(stock).read_text())
    assert "old-mechanism" not in json.dumps(state["facts"])
    assert "folded-under-the-old-layout" not in json.dumps(state["window"])
    assert "old-layout-command" not in json.dumps(state["raw_cmds"])
    assert sorted(Knowledge.load(ctx.repo.label, ctx.mech_dir).facts) == ["source-observed"]
    # What #329's change does not touch is still there, line for line.
    assert "form_repair:run_tests:pytest" in envfacts_state(ctx)["facts"]
    assert ctx.store.read_lines("ledger.jsonl")[:len(ledger)] == ledger
    assert ctx.store.read_lines("knowledge_log.jsonl")[:len(log)] == log
    # A later fold finds nothing left to discard: the stock it wrote is its own.
    fold_mixed(tmp_path, env, repo, monkeypatch, [CARD], sessions=1,
               TE_KNOWLEDGE="on", TE_MICROSKILLS="envfacts", TE_MICROSKILLS_PROPOSE_EVERY="1")
    assert sorted(Knowledge.load(ctx.repo.label, ctx.mech_dir).facts) == ["source-observed"]
    assert "form_repair:run_tests:pytest" in envfacts_state(ctx)["facts"]


def test_the_sweep_removes_only_what_the_layout_cannot_read(tmp_path):
    """Criterion 4: a stock of four-field cards is this layout's own and stays; a file holding
    anything else goes, and the store is swept once."""
    stock = Path(tmp_path, "knowledge_state")
    stock.mkdir()
    (stock / "card.json").write_text(json.dumps({"facts": {"source-observed": CARD}}))
    (stock / "old.json").write_text(json.dumps(OLD_STOCK))
    (stock / "unreadable.json").write_text("{not json")
    assert reset_stock(tmp_path) == ["old.json", "unreadable.json"]
    assert [path.name for path in stock.glob("*.json")] == ["card.json"]
    (stock / "old.json").write_text(json.dumps(OLD_STOCK))
    assert reset_stock(tmp_path) == []        # on this layout now: the sweep has run


def test_a_session_state_does_not_restore_a_block_the_stock_no_longer_holds(
        tmp_path, env, repo, monkeypatch):
    """Criterion 4: an old block is not restored into the new flow. A session that was given
    one comes back without it, and without an error."""
    from tokeneconomizer.plugin.hosts import ClaudeCode
    monkeypatch.setattr(ClaudeCode, "knowledge_start_context", True)
    monkeypatch.setattr(ClaudeCode, "keeps_start_context", False)
    enabled = dict(env, TE_KNOWLEDGE="on", TE_MICROSKILLS="off", TE_LOOPGUARD="off",
                   TE_TOOLPRUNE="off")
    ctx = context_in(enabled, repo)
    Path(Knowledge._path(ctx.mech_dir, ctx.repo.label)).write_text(json.dumps(OLD_STOCK))
    ctx.store.write("sessions/legacy.json", {
        "session_id": "legacy", "cwd": repo, "knowledge_tokens": 12,
        "knowledge_given": ["old-mechanism"],
        "knowledge_startup": {"cards": ["old-mechanism"], "tokens": 12}})
    resumed = json.dumps(call(enabled, {"hook_event_name": "SessionStart", "source": "resume",
                                        "session_id": "legacy", "cwd": repo}))
    assert "an old mechanism" not in resumed
    state = ctx.store.read("sessions/legacy.json")
    assert state["knowledge_startup"]["cards"] == [] and state["knowledge_given"] == []
    assert not (Path(enabled["TOKENECONOMIZER_HOME"]) / "errors.log").exists()


# ---- criterion 5: an installation with both memories restarts and learns again -----------
def test_an_installation_with_both_memories_restarts_and_learns_again(
        tmp_path, env, repo, monkeypatch):
    """Criterion 5: a store holding the micro-skills and the Knowledge restarts with both, and
    a later session's proposal lands in the new stock and is delivered."""
    other = {"id": "support-observed", "claim": "Support is observed",
             "injection": "Support is observed", "detector": [{"path": "support.txt"}]}
    settings = dict(TE_KNOWLEDGE="on", TE_MICROSKILLS="envfacts",
                    TE_MICROSKILLS_PROPOSE_EVERY="1")
    enabled = fold_mixed(tmp_path, env, repo, monkeypatch, [CARD], sessions=6, **settings)
    ctx = context_in(enabled, repo)
    assert "form_repair:run_tests:pytest" in envfacts_state(ctx)["facts"]
    assert sorted(Knowledge.load(ctx.repo.label, ctx.mech_dir).facts) == ["source-observed"]
    # The restart: the native fact comes with the start context, the card with the read.
    restart = read(enabled, repo, "restart", "source.txt")
    assert "fails here with command not found" in restart
    assert "Source is observed" in restart
    # Re-learning: another session proposes a second card into the same store.
    fold_mixed(tmp_path, env, repo, monkeypatch, [other], sessions=1, **settings)
    assert sorted(Knowledge.load(ctx.repo.label, ctx.mech_dir).facts) == [
        "source-observed", "support-observed"]
    assert "Support is observed" in read(enabled, repo, "later", "support.txt")
