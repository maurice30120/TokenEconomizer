"""The proposer's digest of recent work: the newest work sequences, and what each one read.

A work sequence is one real user message and the work that follows it, up to the next message or
the end of the session (GLOSSARY). The digest keeps the `SEQUENCES` newest sequences by message
emission time across every session folded so far: a session folded late with older prompts lands
where its times put it, two prompts of one session are two sequences, and a message that read
nothing still takes its slot.

Each sequence retains the observations its reads produced, in read order, while they fit its own
`BUDGET` characters: the first unit that would not fit ends retention, so neither it nor anything
after it can be cited, and a sequence keeps nothing when its first unit is already too large.

Two reads are the same code when the whole-file version they observed is the same, so they share
one catalogue unit: an identical repeat only adds its ref, an overlapping partial read widens the
unit's range, and a complete read subsumes the partial reads of that version. The unit is what the
budget charges and what a proposal cites, so repeated code is neither shown nor charged twice. A
read of another version is another unit, even when a symbol's tokens survived a line shift: an
identical symbol fingerprint is not proof of the same snapshot.

Every read has a stable `ref`; a Knowledge proposal cites refs, never paths, so `evidence`
resolves a ref against the retained digest alone and a fragment the budget dropped (`out-of-digest`)
proves nothing. The counts of reads, work sequences and sessions, and the pairs of paths read in
one sequence, are signals for the proposer: nothing in this module lets a pair admit anything.

A sequence also keeps what the agent itself wrote (GLOSSARY: Knowledge Comment), attached to
the reads of the call series it followed: its text counts in the same budget, identical comments
deduplicate with their occurrences and their provenance, and none of them is ever a proof.

Everything here is deterministic: no filesystem order, no set iteration, no wall clock.
"""
from ..trace.claude import claude_prompts, claude_replies
from ..trace.copilot import copilot_prompts
from ..trace.pi import pi_prompts, pi_replies
from .observation import reads, records
from .proof import symbol_proof

SEQUENCES = 8        # work sequences in the digest, newest by message emission time
BUDGET = 16_000      # characters one sequence may retain, its message context included
MESSAGE_CAP = 2_000  # characters of a user message kept as its sequence's context
VERSION_CHARS = 12   # how much of a version the proposer is shown
PAIRS = 32           # pairs of paths read in one sequence, most recurrent first


def session_sequences(transcript, root, iid, host="claude", captures=None):
    """The work sequences of one finished session, oldest message first.

    `transcript` is what the agent logged and `root` the workspace the reads are proved against;
    `captures` is that session's Pi capture directory, if any. A read belongs to the sequence its
    own user message opened -- one before the first message belongs to none and is dropped. A
    comment belongs to the reads of the call series it followed: see `_attach`.
    """
    events = records(transcript, host)
    prompts = sorted(_prompts(events, host), key=lambda prompt: prompt[0])
    found = reads(events, root, host=host, captures=captures)
    replies = sorted(_replies(events, host), key=lambda reply: reply[0])
    sequences = [{"id": f"{iid}/{n}", "session": iid, "index": n, "emitted": emitted,
                  "message": _context(text), "units": []}
                 for n, (_position, emitted, text) in enumerate(prompts)]
    stream = ([(position, "prompt", None) for position, _emitted, _text in prompts]
              + [(position, "reply", (calls, text)) for position, calls, text in replies]
              + [(position, "read", read) for position, read in found])
    opened, upcoming, series = -1, 0, []
    observed = [[] for _ in sequences]
    for position, kind, payload in sorted(stream, key=lambda item: item[0]):
        while upcoming < len(prompts) and prompts[upcoming][0] < position:
            opened, upcoming = upcoming, upcoming + 1
        if kind == "prompt":
            series = []
        elif opened >= 0 and kind == "reply":
            calls, text = payload
            if calls:
                series = []
            elif text.strip() and series:
                _attach(sequences[opened], observed[opened], position, text, series)
        elif opened >= 0:
            observed[opened].append(payload)
            series.append(len(observed[opened]) - 1)
    for sequence, mine in zip(sequences, observed):
        sequence["units"] = _retain(sequence, _units(sequence, mine))
    return sequences


def unit_chars(unit):
    """What one retained unit costs its sequence's budget: the code it kept, the path and the refs
    it names, and the comments the reads it absorbed were followed by."""
    return (len(unit["path"]) + sum(len(ref) for ref in unit["refs"])
            + len(unit.get("content") or "")
            + sum(len(comment["text"]) for comment in unit.get("comments") or ()))


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


def _replies(events, host):
    """The messages the agent itself wrote, in log order, as `(position, calls, text)`. Copilot
    has no assistant-message reader, so it reports none; see `knowledge/README.md`."""
    if host == "pi":
        return pi_replies(events)
    return claude_replies(events) if host == "claude" else []


def _context(text):
    """A user message as the digest keeps it: whitespace collapsed and bounded."""
    text = " ".join((text or "").split())
    return text if len(text) <= MESSAGE_CAP else text[:MESSAGE_CAP - 1] + "\u2026"


def _version(unit):
    """The whole-file version a unit observed: what a complete read proved, or the version a Pi
    partial read was captured on. Two units hold the same code only when these are equal."""
    return unit.get("version") if unit.get("partial") else (unit.get("proof") or {}).get("sha256")


def _span(unit):
    """The lines of the file a partial unit kept, as `(first, end)`: one read returns one
    contiguous range, and a merged unit the range that covers the reads it merged."""
    read = unit["observed"]["reads"][0]
    return read["offset"], read["offset"] + read["lines"]


def _lines(unit):
    """A partial unit's retained text by the line number it holds in the file."""
    first, _end = _span(unit)
    return dict(enumerate(unit["content"].split("\n"), first))


def _merge(existing, unit):
    """The unit two reads of one path share, or None when they observed different code.

    A complete read answers for the whole file, so it subsumes every partial read of that
    version. Two partial reads share a unit only when their ranges overlap, and then the unit
    keeps the lines either of them returned -- the same bytes, since the version is the same.
    Another version never merges, however little changed: a symbol whose tokens survived a line
    shift has the same fingerprint and is still another snapshot. A merge keeps what the agent
    said about either read: the comments travel with the unit, in read order.
    """
    if existing["path"] != unit["path"] or _version(unit) is None \
            or _version(existing) != _version(unit):
        return None
    refs = existing["refs"] + unit["refs"]
    if not existing.get("partial") or not unit.get("partial"):
        whole = existing if not existing.get("partial") else unit
        return dict(whole, refs=refs, **_said(existing, unit))
    first, end = _span(existing)
    start, last = _span(unit)
    if start >= end or first >= last:
        return None
    kept = _lines(existing)
    for number, text in _lines(unit).items():
        kept.setdefault(number, text)
    start, end = min(first, start), max(end, last)
    return {"path": existing["path"], "refs": refs, "partial": True,
            "version": existing["version"],
            "content": "\n".join(kept[number] for number in range(start, end)),
            "symbols": dict(existing.get("symbols") or {}, **unit.get("symbols") or {}),
            "observed": {"reads": [{"offset": start, "lines": end - start}],
                         "total_lines": unit["observed"]["total_lines"]},
            **_said(existing, unit)}


def _said(first, second):
    """The comments of two reads that became one unit, in read order: merging code never drops
    what the agent said about either of the reads it absorbed."""
    comments = list(first.get("comments") or []) + list(second.get("comments") or [])
    return {"comments": comments} if comments else {}


def _units(sequence, found):
    """A sequence's reads as the units it may retain, in read order.

    Each read takes the ref of its own rank in the sequence -- a unit the budget drops leaves a
    gap, never a silent replacement -- and reads of one path on one version share a unit, so a
    repeated read costs its characters once and keeps its own ref and provenance. The comments a
    read was followed by travel with it, so a unit that absorbed it keeps them (`_merge`).
    """
    units = []
    for rank, read in enumerate(found):
        unit = {key: value for key, value in read["record"].items() if key != "excerpt"}
        unit["path"] = read["path"]
        unit["refs"] = [f"{sequence['id']}.{rank}"]
        if read.get("comments"):
            unit["comments"] = list(read["comments"])
        for index, existing in enumerate(units):
            merged = _merge(existing, unit)
            if merged is not None:
                units[index] = merged
                break
        else:
            units.append(unit)
    return units


def _attach(sequence, found, position, text, ranks):
    """Attach one visible comment to the reads its call series returned: `ranks` are those reads'
    ranks in the sequence, and each becomes a ref the comment is about. The last read of the
    series owns the record, so the budget counts the text once and `_merge` keeps it with the
    unit that read became: a comment rides on a read, not on a unit, so consolidation cannot lose
    it.
    """
    refs = []
    for rank in ranks:
        ref = f"{sequence['id']}.{rank}"
        if ref not in refs:
            refs.append(ref)
    found[ranks[-1]].setdefault("comments", []).append(
        {"text": text, "refs": refs, "position": position})


def _retain(sequence, units):
    """The units a sequence keeps: the first ones in read order while they fit its budget.

    The first unit that would push the sequence past `BUDGET` ends retention, so it is dropped
    and so is every later one, however small. A first unit already too large therefore leaves the
    sequence with no retained observation, and no sequence borrows from another's budget.
    """
    kept, used = [], len(sequence["message"])
    for unit in units:
        size = unit_chars(unit)
        if used + size > BUDGET:
            break
        used += size
        kept.append(unit)
    return kept


def _order(sequence):
    """Oldest first by message time; a message whose host recorded no time sorts after the dated
    ones, by session and position, so the order stays deterministic."""
    if sequence.get("emitted") is None:
        return (1, 0.0, sequence["session"], sequence["index"])
    return (0, sequence["emitted"], sequence["session"], sequence["index"])


def _fragment(fragment):
    """One contiguous region of a catalogue entry, with the lines it holds and the refs of the
    reads that returned them."""
    return {"refs": fragment["refs"], "observed_lines": observed_lines(fragment),
            "symbols": sorted(fragment.get("symbols") or {}), "text": fragment["content"]}


def _fragments(members):
    """The disjoint regions of one entry: the partial reads of one version whose ranges touch
    share a fragment, and a fragment that does not touch another stays its own."""
    merged = []
    for _sequence, unit in members:
        for index, fragment in enumerate(merged):
            combined = _merge(fragment, unit)
            if combined is not None:
                merged[index] = combined
                break
        else:
            merged.append(dict(unit))
    return [_fragment(fragment) for fragment in merged]


def _read_rank(ref):
    """The rank of the read a ref names, inside its sequence: what keeps refs in read order."""
    return int(ref.rsplit(".", 1)[-1])


def _refs(members):
    """Every ref an entry keeps, in read order: sequence by sequence in the digest's own order,
    and inside a sequence the order the reads were made."""
    by_sequence = {}
    for sequence, unit in members:
        by_sequence.setdefault(sequence["id"], []).extend(unit["refs"])
    return [ref for refs in by_sequence.values() for ref in sorted(refs, key=_read_rank)]


def _entry(members):
    """One catalogue entry: the code of one path on one compatible version, however many reads
    and sequences observed it, with the refs of every one of them."""
    path, version = members[0][1]["path"], _version(members[0][1])
    refs = _refs(members)
    counts = {"reads": len(refs),
              "sequences": len(dict.fromkeys(s["id"] for s, _unit in members)),
              "sessions": len(dict.fromkeys(s["session"] for s, _unit in members))}
    whole = next((unit for _sequence, unit in members if not unit.get("partial")), None)
    if whole is not None:
        return {"path": path, "version": version[:VERSION_CHARS], "refs": refs,
                "counts": counts, "text": whole["content"]}
    fragments = _fragments(members)
    entry = {"path": path, "version": version[:VERSION_CHARS], "refs": refs, "counts": counts}
    if len(fragments) == 1:
        entry.update(fragments[0])
    else:
        entry["fragments"] = fragments
    return entry


def _catalogue(shown):
    """The retained observations as the catalogue the proposer reads: one entry per path and
    compatible version, in first-appearance order, sequence then read.

    The same code appears once and keeps every ref, in read order, so a proposal still names the
    read and the session it means and each ref resolves to the observation it was taken from.
    """
    groups = {}
    for sequence, unit in shown:
        groups.setdefault((unit["path"], _version(unit)), []).append((sequence, unit))
    return [_entry(members) for members in groups.values()]


def _counts(sequences):
    """What the digest holds, distinguished: the reads the catalogue kept, the work sequences it
    covers (a sequence that read nothing is still one), and the sessions they came from."""
    return {"reads": sum(len(unit["refs"]) for sequence in sequences
                         for unit in sequence["units"] if citable(unit)),
            "sequences": len(sequences),
            "sessions": len(dict.fromkeys(sequence["session"] for sequence in sequences))}


def _cooccurrence(sequences):
    """Which paths were read in the same work sequence, and in how many sequences.

    A signal that two files were explored together -- converging explorations worth a look --
    never evidence that they are related: nothing here can back a proposal, and `evidence` never
    reads it. Most recurrent first, then by path, so the list is deterministic.
    """
    counts = {}
    for sequence in sequences:
        paths = sorted({unit["path"] for unit in sequence["units"] if citable(unit)})
        for index, first in enumerate(paths):
            for second in paths[index + 1:]:
                counts[(first, second)] = counts.get((first, second), 0) + 1
    pairs = [{"paths": [first, second], "sequences": count}
             for (first, second), count in counts.items()]
    return sorted(pairs, key=lambda pair: (-pair["sequences"], pair["paths"]))[:PAIRS]


def _comments(sequences):
    """The agent's own comments as the proposer reads them: what it wrote, the refs of the
    retained observations it is about, how many times it wrote exactly that, and where. A comment
    about no citable retained observation cannot be shown -- its refs would point at text the
    digest does not hold -- so it is left out, and one written twice is one entry with two
    occurrences. Nothing a comment says is a proof.
    """
    entries, found = [], {}
    for sequence in sequences:
        shown = [ref for unit in sequence["units"] if citable(unit) for ref in unit["refs"]]
        for unit in sequence["units"]:
            for comment in unit.get("comments") or ():
                refs = [ref for ref in comment["refs"] if ref in shown]
                if not refs:
                    continue
                entry = found.get(comment["text"])
                if entry is None:
                    entry = found[comment["text"]] = {"text": comment["text"], "refs": [],
                                                       "occurrences": 0, "provenance": []}
                    entries.append(entry)
                entry["occurrences"] += 1
                entry["refs"] += [ref for ref in refs if ref not in entry["refs"]]
                entry["provenance"].append({"session": sequence["session"],
                                            "sequence": sequence["id"],
                                            "position": comment["position"]})
    return entries


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
        """What the proposer sees: the sequences (id, session, bounded message, ordered refs), the
        catalogue of the code they read, oldest first, the agent's own comments next to the refs
        they are about, and the counts and pairs that are signals only."""
        shown = [(sequence, unit) for sequence in self.sequences
                 for unit in sequence["units"] if citable(unit)]
        return {"sequences": [{"id": s["id"], "session": s["session"], "message": s["message"],
                               "refs": sorted((ref for unit in s["units"] if citable(unit)
                                               for ref in unit["refs"]), key=_read_rank)}
                              for s in self.sequences],
                "excerpts": _catalogue(shown),
                "comments": _comments(self.sequences),
                "counts": _counts(self.sequences),
                "cooccurrence": _cooccurrence(self.sequences)}

    def evidence(self, entry, root):
        """Resolve one proposal entry (`{ref, symbol?}`) against the retained digest: the contract
        proving what the source says and the session it was observed in, or a reason it cannot
        back the fact.

        A ref that no citable retained observation carries -- unknown, dropped by a sequence's
        budget, or never shown because no symbol its lines crossed could prove it -- is
        `out-of-digest`, so a fragment the proposer was not shown proves nothing. A partial
        read proves only a declaration its lines crossed and never falls back to the file
        (`partial-needs-symbol`, `symbol-not-observed`), and a ref never answers through a
        sibling fragment of the same entry. The proof is returned unverified:
        `Knowledge._admit` checks it again (`stale-proof`).
        """
        units = [(sequence["session"], unit) for sequence in self.sequences
                 for unit in sequence["units"]
                 if entry["ref"] in unit["refs"] and citable(unit)]
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
