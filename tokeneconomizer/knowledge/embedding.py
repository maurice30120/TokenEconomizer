"""The vectorizer a search runs on when nobody configures one, and the shape a model must meet.

`CLAUDE.md` allows the standard library and Tree-sitter, so this module holds a lexical
vectorizer rather than a learned model: a text becomes the counts of its words and of the
three-character fragments of its words, each hashed into one bucket of a fixed-size vector, and
two texts are as near as the cosine of those vectors. It finds a request that reuses a card's
words without naming its signal (`where are the settings stored?` for a card about
`config.json`), and it joins nothing whose words differ -- a French request reaches no English
card. Cross-language semantics are not here and are not claimed: #335's campaign chooses the
model, the vectors and the similarity that decides a request is about a card.

The buckets come from `zlib.crc32`, not `hash`: the index keeps its vectors on disk, and a
per-process seed would score the next session's request in a space the stored vectors do not
share. An embedder is any object with a `name` and an `embed(texts)` returning one vector -- a
list of numbers -- per text; a model #335 plugs in replaces this class at `Knowledge.embedder`
and its name alone makes every stored vector be rebuilt.
"""
import math
import re
import zlib

DIMENSIONS = 512      # buckets per vector: small enough to keep in a JSON file beside the stock
FRAGMENT = 3          # characters per word fragment; shorter ones collide, longer ones are rare
_WORD = re.compile(r"[^\W_]+", re.UNICODE)      # letters and digits, any script, no underscore


def _bucket(feature):
    """The bucket one feature falls into: stable across processes, machines and runs."""
    return zlib.crc32(feature.encode("utf-8")) % DIMENSIONS


class HashingEmbedder:
    """Word and word-fragment counts, hashed into a fixed number of buckets.

    A word counts once more than it occurs, logarithmically, so that repeating a word does not
    drown the rest; its fragments count the same way, which is what makes `settings` and
    `setting` near each other.
    """

    name = "hashing-lexical/1"

    def embed(self, texts):
        """One vector per text, in the order they were given."""
        return [self.vector(text) for text in texts]

    def vector(self, text):
        """The vector of one text: its features counted, then filed into their buckets."""
        counts = {}
        for word in _WORD.findall((text or "").lower()):
            features = ["w:" + word]
            features += ["c:" + word[at:at + FRAGMENT]
                         for at in range(len(word) - FRAGMENT + 1)]
            for feature in features:
                counts[feature] = counts.get(feature, 0) + 1
        out = [0.0] * DIMENSIONS
        for feature, count in counts.items():
            out[_bucket(feature)] += 1.0 + math.log(count)
        return out
