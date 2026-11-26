"""One repository's Knowledge stock, shared by the checkouts of it on this host.

Spec #329: two clones or worktrees of one repository, on one host, share the Knowledge stock,
and a card's validity is computed against the code of the checkout that reads it. The stock is
still one repository's own, and one memory type's own.

The flows run through the plugin's hooks, as a session does, and read the store beside them the
way `te microskills` does.
"""
import json
from pathlib import Path

from tokeneconomizer.knowledge.stage import Knowledge
from tests.test_knowledge_workflow import _learn_source_knowledge, fold_sessions
from tests.test_live_hooks import call, env, repo, store_for  # noqa: F401

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
