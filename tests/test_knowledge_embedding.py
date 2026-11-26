"""The backend a search runs on when nobody configures one (#334).

`CLAUDE.md` allows the standard library and Tree-sitter, and spec #329 leaves the choice of an
embedding model to #335's campaign, so what ships is a lexical vectorizer: words and word
fragments hashed into a fixed-size vector, compared by cosine. It finds a request that reuses a
card's words without naming its signal, and it is deaf across languages -- the tests below say
both, so that the README's claim and the product are the same claim.
"""
import os
import subprocess
import sys
from pathlib import Path

from tests.test_knowledge_index import CONFIG, TESTS, stock

ROOT = Path(__file__).resolve().parents[1]


def two_cards(tmp_path):
    return stock(tmp_path, {"config.json": "settings = 1\n", "tests.txt": "pytest -q\n"},
                 [CONFIG, TESTS])


def test_a_request_reusing_a_cards_words_reaches_it_without_naming_its_signal(tmp_path):
    """What the shipped backend can do: `where are the settings stored?` names no signal of the
    card about `config.json`, and the shared words are enough to rank it. A request that shares
    nothing with it still reaches nothing."""
    stage = two_cards(tmp_path)
    assert "Settings live in config.json" in stage.render("where are the settings stored?")
    assert "Settings live in config.json" not in stage.render("make the spinner faster")


def test_the_shipped_backend_joins_nothing_across_languages(tmp_path):
    """What it cannot do, and does not claim: a French request shares no word with an English
    card, so it reaches nothing. Cross-language semantics are #335's, not this backend's."""
    stage = two_cards(tmp_path)
    assert stage.render("où sont les réglages ?") == ""


def vector_in_another_process(seed):
    """The vector of one text, computed by a fresh interpreter under this hash seed."""
    script = ("from tokeneconomizer.knowledge.embedding import HashingEmbedder\n"
              "print(HashingEmbedder().embed(['the fold discards a stock once'])[0])")
    return subprocess.run([sys.executable, "-c", script], cwd=str(ROOT), text=True,
                          capture_output=True, check=True,
                          env=dict(os.environ, PYTHONHASHSEED=seed)).stdout


def test_a_vector_is_the_same_in_every_process_that_computes_it():
    """The index keeps its vectors between sessions: a hash seeded per process would score the
    next session's request in a space the stored vectors do not share."""
    assert vector_in_another_process("0") == vector_in_another_process("1")
