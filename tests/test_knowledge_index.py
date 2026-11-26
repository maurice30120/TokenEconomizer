"""The Knowledge index and the nearness ranking that reads it (#334).

The backend the plugin ships is tested where it is: `test_knowledge_embedding.py`. What this
file tests is the index around any backend -- built from the stock, rebuilt when the stock or
the embedder changes, kept beside the stock and never trusted with a verdict -- and, through
`FakeEmbedder`, the seam a model #335's campaign chooses plugs into. The fake's "learning" is a
hand-written table of topics in two languages: it stands for a model that could join a French
request to an English claim, which the shipped lexical backend cannot, and it measures no
model's quality. No number here measures one: spec #329 leaves the choice of model, and of the
similarity a request must reach, to #335.
"""
import json
import os
import subprocess
from pathlib import Path

from tokeneconomizer.knowledge.stage import Knowledge
from tests.test_knowledge_workflow import observed_stage, proposal

# The fake's whole "learning". A real model would place these words by training; here a table
# says so, which is exactly the difference this file must not blur.
TOPICS = {
    "config": ("config", "configuration", "settings", "réglages", "reglages", "réglage"),
    "source": ("source", "sources", "fichier", "fichiers", "file", "files"),
    "test": ("test", "tests", "pytest", "vérifie", "verifie"),
}


class FakeEmbedder:
    """A stand-in for a model plugged in at the seam: one dimension per topic of `TOPICS`.

    Its two-language table is the model it stands for, not a backend that ships: `TOPICS` joins
    French to English because it was written that way, and the shipped `HashingEmbedder` joins
    no such pair (`test_knowledge_embedding.py` states both halves). `before` runs before each
    batch is turned into vectors, with the batch it is about to vectorise: a test uses it to
    change the code between the ranking and the delivery.
    """

    name = "fake-topics"

    def __init__(self, before=None):
        self.before = before
        self.batches = []

    def embed(self, texts):
        self.batches.append(list(texts))
        if self.before is not None:
            self.before(list(texts))
        return [[float(sum(1 for word in words if word in text.lower()))
                 for words in TOPICS.values()] for text in texts]


class BrokenEmbedder:
    """A model that cannot answer: what a campaign's real backend does when it is unavailable."""

    name = "broken"

    def embed(self, texts):
        raise RuntimeError("the model is not available")


class ShortEmbedder:
    """A backend answering a different number of vectors than the texts it was given."""

    name = "short"

    def embed(self, texts):
        return [[]] * (len(texts) - 1)


def stock(tmp_path, files, cards):
    """A stage holding these admitted cards, filed where a session reads it: admission runs
    against the observed files, then the stock is saved and read back as a session reads it."""
    stage = observed_stage(tmp_path, files)
    for card in cards:
        assert stage._admit(proposal(**card)) == (True, "admitted")
    stage.save(tmp_path)
    loaded = Knowledge.load("repo", tmp_path)
    loaded.workspace = tmp_path
    return loaded


CONFIG = {"id": "settings", "claim": "Settings live in config.json",
          "injection": "Settings live in config.json", "detector": [{"path": "config.json"}]}
TESTS = {"id": "tests", "claim": "Tests run with pytest",
         "injection": "Tests run with pytest", "detector": [{"path": "tests.txt"}]}


def two_cards(tmp_path):
    return stock(tmp_path, {"config.json": "settings = 1\n", "tests.txt": "pytest -q\n"},
                 [CONFIG, TESTS])


def test_a_model_plugged_in_at_the_seam_can_rank_across_languages(tmp_path):
    """The seam's whole point: `render` has no model of its own, so an embedder given to it is
    what lets a request reach a card no string match joins. The fake stands for a model with
    cross-language meaning; the shipped backend has none, and joins only what shares its words."""
    stage = two_cards(tmp_path)
    assert stage.render("où sont les réglages ?") == ""      # no signal, and no shared word
    stage.embedder = FakeEmbedder()
    block = stage.render("où sont les réglages ?")
    assert "Settings live in config.json" in block
    assert "Tests run with pytest" not in block


def test_a_named_card_comes_before_a_card_the_request_is_only_near(tmp_path):
    """Nearness adds to the exact signals; it does not reorder them, and with room for one card
    it does not displace the named one."""
    stage = two_cards(tmp_path)
    stage.embedder = FakeEmbedder()
    block = stage.render("check config.json and the pytest run", max_tokens=300)
    assert block.index("Settings live in config.json") < block.index("Tests run with pytest")
    only_named = stage.render("check config.json and the pytest run", max_facts=1, max_tokens=300)
    assert "Settings live in config.json" in only_named
    assert "Tests run with pytest" not in only_named


def test_without_an_embedder_the_exact_signals_alone_rank_and_no_index_is_written(
        tmp_path, monkeypatch):
    """Configured as none -- the seam closed -- the ranking is the one the plugin always had and
    no index file is written. The shipped backend is not this state: see
    `test_knowledge_embedding.py`."""
    from tokeneconomizer.knowledge.index import index_path
    monkeypatch.setattr(Knowledge, "embedder", None)
    stage = two_cards(tmp_path)
    assert "Settings live in config.json" in stage.render("look at config.json")
    assert "Settings live in config.json" in stage.render("look at ./config.json")
    assert stage.render("où sont les réglages ?") == ""
    assert not os.path.exists(index_path(tmp_path, "repo"))
    assert not (tmp_path / "knowledge_index").exists()


def test_the_index_is_kept_beside_the_stock_with_no_verdict_in_it(tmp_path):
    """Its on-disk name and shape: `<store>/knowledge_index/<repo>.json`, one entry per card
    holding what a ranking needs -- and nothing that says whether a card holds."""
    from tokeneconomizer.knowledge.index import index_path
    stage = two_cards(tmp_path)
    stage.embedder = FakeEmbedder()
    stage.render("où sont les réglages ?")
    path = index_path(tmp_path, "repo")
    assert path == str(tmp_path / "knowledge_index" / "repo.json")
    with open(path, encoding="utf-8") as stream:
        doc = json.load(stream)
    assert (doc["repo"], doc["embedder"]) == ("repo", "fake-topics")
    assert sorted(doc["cards"]) == ["settings", "tests"]
    entry = doc["cards"]["settings"]
    assert sorted(entry) == ["claim", "injection", "paths", "signals", "vector"]
    assert (entry["claim"], entry["injection"]) == ("Settings live in config.json",
                                                    "Settings live in config.json")
    assert (entry["paths"], entry["signals"]) == (["config.json"], ["config.json"])
    assert len(entry["vector"]) == len(TOPICS)
    # The stock itself is untouched by the index: the four fields and the internal block.
    with open(tmp_path / "knowledge_state" / "repo.json", encoding="utf-8") as stream:
        state = json.load(stream)
    assert sorted(state["facts"]["settings"]) == ["claim", "detector", "id", "injection",
                                                  "internal"]


def test_the_index_is_rebuilt_when_a_card_is_admitted(tmp_path):
    """A card admitted after the index was built is ranked at the next search, and the file on
    disk describes the stock it was read from."""
    from tokeneconomizer.knowledge.index import index_path
    stage = stock(tmp_path, {"config.json": "settings = 1\n", "tests.txt": "pytest -q\n"},
                  [CONFIG])
    stage.embedder = FakeEmbedder()
    assert "Settings live in config.json" in stage.render("où sont les réglages ?")
    path = index_path(tmp_path, "repo")
    with open(path, encoding="utf-8") as stream:
        assert sorted(json.load(stream)["cards"]) == ["settings"]
    assert stage._admit(proposal(**TESTS)) == (True, "admitted")
    block = stage.render("y a-t-il un test ?")
    assert "Tests run with pytest" in block
    assert "Settings live in config.json" not in block
    with open(path, encoding="utf-8") as stream:
        assert sorted(json.load(stream)["cards"]) == ["settings", "tests"]


def test_a_ranking_that_cannot_run_leaves_the_exact_signals_as_the_whole_ranking(tmp_path):
    """A model that is down, or one whose vectors are the wrong shape, costs the search only what
    it added: the seam is entered and declines (`broken`, no index written), and every card the
    exact signals gave is still delivered."""
    from tokeneconomizer.knowledge.index import index_path
    stage = two_cards(tmp_path)
    for embedder in (BrokenEmbedder(), ShortEmbedder()):
        stage.embedder = embedder
        assert stage.index().broken is True
        assert not os.path.exists(index_path(tmp_path, "repo"))
        assert "Settings live in config.json" in stage.render("read config.json")
        assert "Tests run with pytest" in stage.render("read tests.txt")
        assert stage.render("où sont les réglages ?") == ""


def test_a_local_edit_leaves_the_ranking_at_the_next_search(tmp_path):
    """Criterion 2 (#334): the cards ranked are those whose contract holds in the checkout as it
    is now, checked at search time. An edit drops the card from the next search; the bytes its
    contract proves bring it back. The stock keeps the card throughout, with no status written
    anywhere."""
    stage = two_cards(tmp_path)
    stage.embedder = FakeEmbedder()
    stock_file = tmp_path / "knowledge_state" / "repo.json"
    before = stock_file.read_bytes()
    assert "Settings live in config.json" in stage.render("où sont les réglages ?")
    config = tmp_path / "config.json"
    config.write_text("settings = 2\n")                     # a local edit
    assert stage.render("où sont les réglages ?") == ""
    assert "settings" in stage.facts                         # still a card of the stock
    assert stock_file.read_bytes() == before                 # and nothing says it is invalid
    config.write_text("settings = 1\n")                     # the bytes the contract proves
    assert "Settings live in config.json" in stage.render("où sont les réglages ?")


def git(root, *argv):
    """One git command in the test's own throwaway repository."""
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", "-C", str(root), *argv],
                   check=True, capture_output=True)


def test_switching_branches_changes_the_ranking_at_the_next_search(tmp_path):
    """Criterion 2 (#334), on a repository with two branches rather than a rewritten file: no
    search consults git -- a card's contract is verified against the bytes in the checkout -- so
    the other version a branch switch puts there drops the card at the next search, and
    switching back restores it. The card is never removed from the stock."""
    (tmp_path / "config.json").write_text("settings = 1\n")
    (tmp_path / "tests.txt").write_text("pytest -q\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "checkout", "-q", "-b", "main")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "main")
    git(tmp_path, "checkout", "-q", "-b", "other")
    (tmp_path / "config.json").write_text("settings = 2\n")
    git(tmp_path, "commit", "-qam", "other")
    git(tmp_path, "checkout", "-q", "main")
    stage = two_cards(tmp_path)                        # admitted against `main`'s bytes
    stage.embedder = FakeEmbedder()
    assert "Settings live in config.json" in stage.render("où sont les réglages ?")
    git(tmp_path, "checkout", "-q", "other")
    assert stage.render("où sont les réglages ?") == ""
    assert "settings" in stage.facts                   # still a card of the stock
    git(tmp_path, "checkout", "-q", "main")
    assert "Settings live in config.json" in stage.render("où sont les réglages ?")


def test_a_change_between_the_ranking_and_the_delivery_drops_the_card(tmp_path):
    """Criterion 2 (#334): validity is decided when the card is delivered, not by the ranking, so
    a file that changes between the search and the block costs that card the search."""
    stage = two_cards(tmp_path)
    stage.embedder = FakeEmbedder()
    assert "Settings live in config.json" in stage.render("où sont les réglages ?")
    config = tmp_path / "config.json"

    def edit(texts):
        if any("réglages" in text for text in texts):        # the request, not the cards
            config.write_text("settings = 2\n")
    stage.embedder = FakeEmbedder(before=edit)
    assert stage.index().near("où sont les réglages ?") == ["settings"]   # still ranked
    assert "Settings live in config.json" not in stage.render("où sont les réglages ?")


def test_a_search_with_no_request_ranks_nothing_and_writes_no_index(tmp_path):
    """A request-less search (the block a session with nothing to match gets) delivers every
    eligible card through the exact path, so it has to rank, embed and write nothing: the index
    is prepared for a request, not for a render."""
    from tokeneconomizer.knowledge.index import index_path
    stage = two_cards(tmp_path)
    embedder = FakeEmbedder()
    stage.embedder = embedder
    block = stage.render(None)
    assert "Settings live in config.json" in block and "Tests run with pytest" in block
    assert embedder.batches == []
    assert not os.path.exists(index_path(tmp_path, "repo"))


def test_a_stored_vector_of_non_numbers_costs_the_nearness_and_no_card(tmp_path):
    """A stored index is derived data, and a vector of anything but numbers is one no ranking can
    read. It must not escape as an exception: the exact signals then deliver exactly what they
    always did, the cards included."""
    from tokeneconomizer.knowledge.index import index_path
    stage = two_cards(tmp_path)
    stage.embedder = FakeEmbedder()
    assert "Settings live in config.json" in stage.render("où sont les réglages ?")
    path = Path(index_path(tmp_path, "repo"))
    doc = json.loads(path.read_text())
    doc["cards"]["settings"]["vector"] = ["not a number"] * 3
    path.write_text(json.dumps(doc))
    reopened = Knowledge.load("repo", tmp_path)
    reopened.workspace = tmp_path
    reopened.embedder = FakeEmbedder()
    assert "Tests run with pytest" in reopened.render("look at tests.txt")
    assert "Settings live in config.json" in reopened.render("look at config.json")
