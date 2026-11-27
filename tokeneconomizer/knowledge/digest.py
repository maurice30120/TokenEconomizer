"""The proposer's digest of recent work: the newest work sequences, and what each one read.

A work sequence is one real user message and the work that follows it, up to the next message or
the end of the session (GLOSSARY). The digest keeps the `SEQUENCES` newest sequences by message
emission time across every session folded so far: a session folded late with older prompts lands
where its times put it, two prompts of one session are two sequences, and a message that read
nothing still takes its slot.

Each sequence retains the observations its reads produced, in read order, while they fit its own
`BUDGET` characters: the first unit that would not fit ends retention, so neither it nor anything
after it can be cited, and a sequence keeps nothing when its first unit is already too large.
Every retained observation has a stable `ref`; a Knowledge proposal cites refs, never paths, so
`evidence` resolves a ref against the retained digest alone and a fragment the budget dropped
(`out-of-digest`) proves nothing.

Everything here is deterministic: no filesystem order, no set iteration, no wall clock.
"""
from ..trace.claude import claude_prompts
from ..trace.copilot import copilot_prompts
from ..trace.pi import pi_prompts
from .observation import reads, records
from .proof import symbol_proof

SEQUENCES = 8        # work sequences in the digest, newest by message emission time
BUDGET = 16_000      # characters one sequence may retain, its message context included
MESSAGE_CAP = 2_000  # characters of a user message kept as its sequence's context
VERSION_CHARS = 12   # how much of a version the proposer is shown


def session_sequences(transcript, root, iid, host="claude", captures=None):
    """The work sequences of one finished session, oldest message first.

    `transcript` is what the agent logged and `root` the workspace the reads are proved against;
    `captures` is that session's Pi capture directory, if any. A read belongs to the sequence its
    own user message opened -- one before the first message belongs to none and is dropped.
    """
    events = records(transcript, host)
    prompts = sorted(_prompts(events, host), key=lambda prompt: prompt[0])
    found = reads(events, root, host=host, captures=captures)
    sequences = [{"id": f"{iid}/{n}", "session": iid, "index": n, "emitted": emitted,
                  "message": _context(text), "units": []}
                 for n, (_position, emitted, text) in enumerate(prompts)]
    opened, upcoming = -1, 0
    for position, read in sorted(found, key=lambda pair: pair[0]):
        while upcoming < len(prompts) and prompts[upcoming][0] < position:
            opened, upcoming = upcoming, upcoming + 1
        if opened >= 0:
            _read_into(sequences[opened], read)
    for sequence in sequences:
        sequence["units"] = _retain(sequence, sequence["units"])
    return sequences


def unit_chars(unit):
    """What one retained unit costs its sequence's budget: the code it kept, the path and ref it
    names, and the agent's comments once they are attached to it (#345)."""
    return (len(unit["path"]) + len(unit["ref"]) + len(unit.get("content") or "")
            + sum(len(comment) for comment in unit.get("comments") or ()))


def citable(unit):
    """Whether a proposal may cite this unit. A partial read that crossed no declaration (an
    unparsed file, no supported extension, no declaration in the lines) could only be refused,
    so the unit stays retained -- a refusal can then say exactly what is missing -- while the
    proposer is neither shown it nor allowed to cite it."""
    return not unit.get("partial") or bool(unit.get("symbols"))


def observed_lines(unit):
    """Which lines of the file a partial observation actually returned."""
    spans = ", ".join(f"{read['offset']}-{read['offset'] + read['lines'] - 1}"
                      for read in unit["observed"]["reads"])
    return f"{spans} of {unit['observed']['total_lines']}"


def _prompts(events, host):
    if host == "pi":
        return pi_prompts(events)
    if host == "copilot":
        return copilot_prompts(events)
    return claude_prompts(events) if host == "claude" else []


def _context(text):
    """A user message as the digest keeps it: whitespace collapsed and bounded."""
    text = " ".join((text or "").split())
    return text if len(text) <= MESSAGE_CAP else text[:MESSAGE_CAP - 1] + "\u2026"


def _identity(unit):
    """What makes two reads of a file the same observation: the same path, the same version of
    it, and the same lines of it (the whole file for a complete read)."""
    if unit.get("partial"):
        return (unit["path"], unit.get("version"),
                tuple((read["offset"], read["lines"]) for read in unit["observed"]["reads"]))
    return (unit["path"], (unit.get("proof") or {}).get("sha256"), None)


def _read_into(sequence, read):
    """Add one read to a sequence as its own unit, unless the sequence already made exactly that
    read. Local deduplication goes no further: a unit carries its own read's text, version and
    symbols, so what it proves is what it showed. Ranges of one file across a sequence are
    merged by #344, not here."""
    unit = {key: value for key, value in read["record"].items() if key != "excerpt"}
    unit["path"] = read["path"]
    if any(_identity(unit) == _identity(other) for other in sequence["units"]):
        return
    sequence["units"].append(unit)


def _retain(sequence, units):
    """The units a sequence keeps: the first ones in read order while they fit its budget.

    The first unit that would push the sequence past `BUDGET` ends retention, so it is dropped
    and so is every later one, however small. A first unit already too large therefore leaves the
    sequence with no retained observation, and no sequence borrows from another's budget.
    """
    kept, used = [], len(sequence["message"])
    for index, unit in enumerate(units):
        retained = dict(unit, ref=f"{sequence['id']}.{index}")
        size = unit_chars(retained)
        if used + size > BUDGET:
            break
        used += size
        kept.append(retained)
    return kept


def _order(sequence):
    """Oldest first by message time; a message whose host recorded no time sorts after the dated
    ones, by session and position, so the order stays deterministic."""
    if sequence.get("emitted") is None:
        return (1, 0.0, sequence["session"], sequence["index"])
    return (0, sequence["emitted"], sequence["session"], sequence["index"])


def _observation(unit):
    """One retained observation as the proposer reads it: the code the sequence's budget kept
    (`content`), which is what `unit_chars` counted, under its ref, path and version."""
    version = unit["version"] if unit.get("partial") else unit["proof"]["sha256"]
    shown = {"ref": unit["ref"], "path": unit["path"], "version": version[:VERSION_CHARS]}
    if unit.get("partial"):
        shown["observed_lines"] = observed_lines(unit)
        shown["symbols"] = sorted(unit.get("symbols") or {})
    shown["text"] = unit["content"]
    return shown


class Digest:
    """The rolling window of work sequences, kept with the Knowledge state."""

    def __init__(self, sequences=()):
        self.sequences = [sequence for sequence in sequences if isinstance(sequence, dict)]

    def absorb(self, sequences):
        """Fold in one finished session's sequences, then keep the `SEQUENCES` newest by message
        time across every session (a re-fold of one session replaces its own sequences)."""
        sequences = list(sequences)
        session = sequences[0]["session"] if sequences else None
        kept = [s for s in self.sequences if s.get("session") != session]
        self.sequences = sorted(kept + sequences, key=_order)[-SEQUENCES:]

    def retained(self):
        """Whether any retained observation could back a proposal."""
        return any(citable(unit) for sequence in self.sequences for unit in sequence["units"])

    def view(self):
        """What the proposer sees: the sequences (id, session, bounded message, ordered refs) and
        the retained observations they cite, oldest first."""
        return {"sequences": [{"id": s["id"], "session": s["session"], "message": s["message"],
                               "refs": [unit["ref"] for unit in s["units"] if citable(unit)]}
                              for s in self.sequences],
                "excerpts": [_observation(unit) for s in self.sequences for unit in s["units"]
                             if citable(unit)]}

    def evidence(self, entry, root):
        """Resolve one proposal entry (`{ref, symbol?}`) against the retained digest: the contract
        proving what the source says and the session it was observed in, or a reason it cannot
        back the fact.

        A ref that no citable retained observation carries -- unknown, ambiguous, dropped by a
        sequence's budget, or never shown because no symbol its lines crossed could prove it --
        is `out-of-digest`, so a fragment the proposer was not shown proves nothing. A partial
        read proves only a declaration its lines crossed and never falls back to the file
        (`partial-needs-symbol`, `symbol-not-observed`). The proof is returned unverified:
        `Knowledge._admit` checks it again (`stale-proof`).
        """
        units = [(sequence["session"], unit) for sequence in self.sequences
                 for unit in sequence["units"]
                 if unit["ref"] == entry["ref"] and citable(unit)]
        if len(units) != 1:
            return None, None, "out-of-digest"
        session, unit = units[0]
        symbol = entry.get("symbol")
        if unit.get("partial"):
            if symbol is None:
                return None, None, "partial-needs-symbol"
            proof = (unit.get("symbols") or {}).get(symbol)
            if proof is None:
                return None, None, "symbol-not-observed"
            return dict(proof, observed=dict(unit["observed"])), session, None
        if symbol is not None:
            content = unit.get("content")
            proof = (symbol_proof(root, unit["path"], content.encode("utf-8"), symbol)
                     if isinstance(content, str) else None)
            if proof is None:
                proof = dict(unit["proof"], kind="file",
                             fallback={"symbol": symbol, "reason": "symbol-unresolvable"})
            return dict(proof), session, None
        return dict(unit["proof"]), session, None

    def state(self):
        """The digest as the Knowledge state stores it, under its own key."""
        return {"sequences": list(self.sequences)}

    @classmethod
    def restore(cls, state):
        """The digest a saved state holds; empty when it holds none."""
        sequences = (state or {}).get("sequences") if isinstance(state, dict) else None
        return cls(sequences if isinstance(sequences, list) else [])
