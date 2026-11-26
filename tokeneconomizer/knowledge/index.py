"""A local index over the Knowledge stock, and the nearness ranking that reads it.

`embedding.HashingEmbedder` ships as the vectorizer: words and word fragments hashed into a
fixed-size vector, so a request that reuses a card's words without naming its signal is ranked
by lexical nearness. It is not a learned model and claims no cross-language meaning -- spec
#329 leaves the choice of a model, and of the similarity at which a request counts as being
about a card, to #335's campaign -- so this module keeps the seam: an index prepared from the
stock and kept beside it, and a ranking that takes whatever embedder is given to it.

An embedder is an object with a `name` and an `embed(texts)` method returning one vector -- a
list of numbers -- per text. Configured as none, `Knowledge.index` is None, no file is written,
and the search ranks by the exact signals it always did.

The index is derived data, never a verdict. It holds each card's id, claim, injection text,
covered paths, signals and the vector of that text; whether a card may be delivered is decided
at search time by `Knowledge.contract_valid`, at the moment the card is chosen. So a file that
changed -- a local edit, or the other version a branch switch puts there -- shows on the next
search, and a card whose code came back becomes eligible again without the index being told
anything.
"""
import hashlib
import json
import os

from ..microskills.lifecycle import write_json_atomic
from ..names import repo_filename

INDEX_DIR = "knowledge_index"     # beside `knowledge_state/`, never inside it
# How near a request must be to a card's text -- the cosine similarity of their vectors -- for
# the card to be ranked at all. The shipped backend's value is calibrated no further than this:
# it joins a paraphrase that reuses a card's words, and joins nothing that shares none of them.
# #335's campaign measures the similarity that decides a card is about a request, for whatever
# model it chooses, and replaces this one with it.
NEAR_SIMILARITY = 0.35


def index_path(root, repo):
    """`<root>/knowledge_index/<repo>.json`: beside the stock, filed by the same repository name.

    Never inside `knowledge_state/`: the stock's own sweep reads that directory, and an index
    that went with it would have to be rebuilt by the first search after every sweep.
    """
    if not root:
        return None
    return os.path.join(root, INDEX_DIR, repo_filename(repo) + ".json")


def _cosine(a, b):
    """The cosine similarity of two vectors; 0 when either is empty or all zero."""
    if not a or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    left = sum(x * x for x in a) ** 0.5
    right = sum(y * y for y in b) ** 0.5
    return dot / (left * right) if left and right else 0.0


class KnowledgeIndex:
    """The stock's texts and vectors, on disk beside it, and the nearness they order.

    `digest` identifies the cards the index describes and `embedder` the model that made the
    vectors: either one changing rebuilds the whole index, so an admitted card is ranked at the
    next search and another model never reads vectors it did not produce.
    """

    def __init__(self, embedder, repo="", path=None):
        self.embedder = embedder
        self.repo = repo
        self.path = path
        self.digest = ""
        self.cards = {}       # id -> {claim, injection, paths, signals, vector}
        self.broken = False   # the ranking could not be built: the exact signals stand alone

    @property
    def name(self):
        """The model this index was built with: another one rebuilds every vector."""
        return str(getattr(self.embedder, "name", "") or type(self.embedder).__name__)

    @staticmethod
    def digest(entries):
        """What the index describes: the cards, their texts, and what their contracts cover."""
        return hashlib.sha256(
            json.dumps(entries, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    @classmethod
    def prepare(cls, path, embedder, repo, entries):
        """The index for these cards: the one on disk when it describes them and the same
        embedder made it, rebuilt -- and re-embedded -- otherwise."""
        index = cls(embedder, repo, path)
        digest = cls.digest(entries)
        stored = index._read()
        if stored.get("digest") == digest and stored.get("embedder") == index.name:
            index.digest, index.cards = digest, stored["cards"]
            return index
        index._build(entries, digest)
        if index.cards and not index.broken:
            index._save()
        return index

    def near(self, task):
        """The ids of the cards this request is near, nearest first, ties in registration order.

        Empty when the index could not be built, when the request is empty, or when the embedder
        cannot answer this one: a search that cannot rank then delivers what the exact signals
        deliver, and nothing more.
        """
        if self.broken or not self.cards or not task:
            return []
        try:
            vectors = self.embedder.embed([task])
            query = [float(x) for x in vectors[0]]
        except Exception:
            return []
        scored = [(-_cosine(query, card["vector"]), order, card_id)
                  for order, (card_id, card) in enumerate(self.cards.items())]
        return [card_id for score, _order, card_id in sorted(scored)
                if -score >= NEAR_SIMILARITY]

    def _build(self, entries, digest):
        """Embed every card's text and keep what the ranking and the inspection need."""
        try:
            vectors = self.embedder.embed([entry["injection"] for entry in entries])
            cards = {}
            for entry, vector in zip(entries, vectors, strict=True):
                cards[entry["id"]] = dict(
                    {key: entry[key] for key in ("claim", "injection", "paths", "signals")},
                    vector=[float(x) for x in vector])
        except Exception:            # a model that fails or answers another shape ranks nothing
            self.broken = True
            return
        self.cards, self.digest = cards, digest

    def _read(self):
        """The index as it was written, {} when there is none or it is not one of ours."""
        if not self.path:
            return {}
        try:
            with open(self.path, encoding="utf-8") as stream:
                doc = json.load(stream)
        except (OSError, ValueError):
            return {}
        cards = doc.get("cards") if isinstance(doc, dict) else None
        if not isinstance(cards, dict) or not all(
                isinstance(card, dict) and isinstance(card.get("vector"), list)
                for card in cards.values()):
            return {}
        return doc

    def _save(self):
        """Write the index beside the stock. An unwritable store costs the index, never the
        search: the next one rebuilds it in memory."""
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            write_json_atomic(self.path, {"repo": self.repo, "embedder": self.name,
                                         "digest": self.digest, "cards": self.cards})
        except OSError:
            pass
