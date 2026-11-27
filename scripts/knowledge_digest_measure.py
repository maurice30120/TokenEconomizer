#!/usr/bin/env python3
"""Measure the Knowledge digest against the mechanism it replaced, on the same Pi traces.

The Knowledge proposer is given a digest of the code the agent already read. Ticket #341 replaced
the per-session `observed_sources` view (one entry per read path, each excerpt cut at 2 000
characters, at most 10 paths per session) with the work-sequence digest
(`tokeneconomizer/knowledge/digest.py`: the `SEQUENCES = 8` newest work sequences, `BUDGET =
16_000` characters each). This harness measures both arms on one set of Pi session logs, so a
later decision about the window and the cap rests on numbers instead of taste.

One trace is one finished session. It is folded through the real Knowledge stage (`Knowledge.load`
then `update`, with the host's own conversion for the digest and the raw log for the observations,
no captures) with a stub proposer: the stub records the prompt and answers `{"facts": []}`, so no
model is called and nothing is generated. The harness then records what that fold put in front of
the proposer and probes admission with three minimal candidates built from the first observation
the arm offers -- the candidate itself, the same claim twice (`duplicate`), and the same candidate
after the file changed (`stale-proof`).

Two arms:

* `current` -- the work-sequence digest of this tree;
* `baseline` -- `--baseline-ref` (default `f1a6c18`, the integration tip after #342 and before
  #343), materialised with `git archive` in a temporary directory outside the repository.

Each arm runs in its own subprocess with `PYTHONPATH` pointing at that arm, because both export
the same module names. Nothing is written outside those temporary directories, no clock is read
and no network is used: the same command on the same traces gives the same JSON.

    PYTHONPATH=$PWD python scripts/knowledge_digest_measure.py \\
        --traces ~/.pi/agent/sessions/<slug> --workspace <repo> [--out /tmp/measure.json]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

ANNEX = "\nFor Knowledge candidates only"        # where every Knowledge prompt starts its annex
CLAIM = "the first observation this digest offers still holds"
DETECTOR = {"scope": "pytest", "confirm": "passed"}
# A measurement leaves no run output in the repository: the report goes to a temporary path.
DEFAULT_OUT = os.path.join(tempfile.gettempdir(), "knowledge-digest-measure.json")
SUMS = ("prompts", "reads", "paths", "prompt.chars", "prompt.tokens", "observation_chars",
        "digest.sequences", "digest.sessions", "digest.reads_kept", "digest.catalogue.entries",
        "digest.catalogue.paths", "digest.catalogue.repeated", "digest.retention.units",
        "digest.retention.kept", "digest.retention.dropped", "digest.retention.overflow",
        "digest.retention.dropped_chars", "digest.retention.windowed_out",
        "digest.retention.windowed_units", "comments.entries", "comments.occurrences",
        "comments.chars", "window.sessions", "window.entries", "window.paths",
        "window.repeated", "window.truncated", "window.excerpt_chars", "window.content_chars")
MAXIMA = ("digest.retention.max_used",)      # a per-fold maximum, summed by nobody


# ---- the traces, read by nobody's rules but the log's own --------------------------------
def traces_of(paths, limit=None):
    """The Pi session logs named by `paths` -- files, or the `*.jsonl` of a directory -- sorted,
    so two runs fold the same sessions in the same order."""
    out = []
    for path in paths:
        if os.path.isdir(path):
            out += [os.path.join(path, name) for name in sorted(os.listdir(path))
                    if name.endswith(".jsonl")]
        else:
            out.append(path)
    return out[:limit] if limit else out


def _entries(path):
    """The log's entries, skipping a line this reader cannot decode (a corrupted tail)."""
    out = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                out.append(entry)
    return out


def _relative(path, workspace):
    """A read path as the digest would name it: workspace-relative inside the workspace."""
    if not isinstance(path, str) or not path:
        return "<no path>"
    full = os.path.realpath(path)
    try:
        inside = os.path.commonpath([os.path.realpath(workspace), full])
    except ValueError:            # different drives on Windows
        return path
    return os.path.relpath(full, os.path.realpath(workspace)) if inside == os.path.realpath(
        workspace) else path


def _trace_facts(entries, workspace):
    """What the log itself shows, whichever arm reads it: how many `read` calls the agent made
    and how many distinct paths they named, on the active branch (the arm's own host adapter
    decides what it can prove of them)."""
    from tokeneconomizer.trace.pi import pi_active_branch
    reads, paths = 0, set()
    for entry in pi_active_branch(entries):
        message = entry.get("message") or {}
        if message.get("role") != "assistant":
            continue
        for block in message.get("content") or ():
            if (isinstance(block, dict) and block.get("type") == "toolCall"
                    and block.get("name") == "read"):
                reads += 1
                paths.add(_relative((block.get("arguments") or {}).get("path"), workspace))
    return {"reads": reads, "paths": len(paths)}


def _session_id(trace):
    """The session id the plugin would fold this log under: Pi's own header id."""
    from tokeneconomizer.trace.pi import pi_session_header
    header = pi_session_header(trace) or {}
    return header.get("id") or os.path.splitext(os.path.basename(trace))[0]


# ---- what each arm shows the proposer ----------------------------------------------------
def _digest_metrics(stage, trace, workspace, session):
    """The work-sequence digest's own numbers for this fold, plus what its budget dropped.

    `units` counts what this session's sequences produced before retention, `kept` what their
    `BUDGET` retained; `overflow` counts the sequences whose retention stopped before their last
    unit -- the case where a later, smaller unit is dropped because an earlier one did not fit.
    """
    from tokeneconomizer.knowledge.digest import BUDGET, SEQUENCES, session_sequences, unit_chars
    view = stage.digest.view()
    offered = view["excerpts"]
    paths = {entry["path"] for entry in offered}
    refs = view["counts"]["reads"]
    mine = [sequence for sequence in stage.digest.sequences if sequence["session"] == session]
    kept = {sequence["id"]: len(sequence["units"]) for sequence in mine}
    folded = _before_budget(trace, workspace, session)   # the same fold, cap lifted
    # A sequence the eight-slot window pushed out was never offered to a budget: it is not an
    # overflow, it is work the window no longer holds.
    present = [sequence for sequence in folded if sequence["id"] in kept]
    units = sum(len(sequence["units"]) for sequence in present)
    retained = sum(kept.values())
    # What the digest's own budget charged: the observations only, as `_retain` does.
    used = {sequence["id"]: sum(unit_chars(unit) for unit in sequence["units"])
            for sequence in mine}
    return {"observation_chars": len(json.dumps(offered, indent=1, ensure_ascii=False))
                              + len(json.dumps(view["comments"], indent=1, ensure_ascii=False)),
            "digest": {"sequences_budget": SEQUENCES, "sequence_char_budget": BUDGET,
                       "sequences": len(mine), "window_sequences": len(stage.digest.sequences),
                       "sessions": view["counts"]["sessions"], "reads_kept": refs,
                       "catalogue": {"entries": len(offered), "paths": len(paths),
                                     "repeated": refs - len(offered)},
                       "retention": {
                           "units": units, "kept": retained, "dropped": units - retained,
                           "overflow": sum(1 for sequence in present
                                           if kept[sequence["id"]] < len(sequence["units"])),
                           "windowed_out": len(folded) - len(present),
                           "windowed_units": sum(len(sequence["units"]) for sequence in folded)
                           - units,
                           "max_used": max(used.values(), default=0),
                           "dropped_chars": sum(unit_chars(unit) for sequence in present
                                                for unit in sequence["units"])
                           - sum(unit_chars(unit) for sequence in mine
                                 for unit in sequence["units"])}},
            "comments": {"entries": len(view["comments"]),
                         "occurrences": sum(c["occurrences"] for c in view["comments"]),
                         "chars": sum(len(c["text"]) for c in view["comments"])}}


def _before_budget(trace, workspace, session):
    """The same session's sequences with the character cap lifted, so the harness can count what
    the budget dropped: the digest keeps no record of a unit it refused. `BUDGET` is read at
    retention time, and is restored before this returns."""
    from tokeneconomizer.knowledge import digest as module
    saved = module.BUDGET
    module.BUDGET = sys.maxsize
    try:
        return module.session_sequences(trace, workspace, session, host="pi")
    finally:
        module.BUDGET = saved


def _window_metrics(stage):
    """The previous mechanism's numbers: the window of session digests, each carrying one
    `observed_sources` entry per read path, its excerpt cut where the prompt cuts it."""
    records = [record for digest in stage.window
               for record in (digest.get("_observations") or {}).values()]
    sources = [source for digest in stage.window
               for source in (digest.get("observed_sources") or ())]
    paths = {source["path"] for source in sources}
    shown = sum(len(record.get("excerpt") or "") for record in records)
    whole = sum(len(record.get("content") or "") for record in records)
    return {"observation_chars": len(json.dumps([digest.get("observed_sources")
                                                 for digest in stage.window],
                                                indent=1, ensure_ascii=False)),
            "window": {"sessions": len(stage.window), "entries": len(sources),
                       "paths": len(paths), "repeated": len(sources) - len(paths),
                       "truncated": sum(1 for record in records
                                        if len(record.get("content") or "")
                                        > len(record.get("excerpt") or "")),
                       "excerpt_chars": shown, "content_chars": whole}}


def _prompt_metrics(prompt, digest_arm):
    """How large the prompt was, and of what. The digest arm writes its view as four labelled
    JSON blocks after the Knowledge mandate; the previous mechanism had no such boundary -- the
    observations rode inside the native digest list -- so only the total is recorded for it."""
    chars = len(prompt)
    out = {"chars": chars, "tokens": (chars + 3) // 4, "blocks": {}}
    if not digest_arm:
        if ANNEX in prompt:
            out["blocks"]["native"] = prompt.index(ANNEX)
            out["blocks"]["mandate"] = chars - prompt.index(ANNEX)
        return out
    from tokeneconomizer.knowledge.stage import (COMMENTS_HEADER, DIGEST_HEADER, EXCERPTS_HEADER,
                                                 SIGNALS_HEADER)
    out["blocks"]["native"] = prompt.index(ANNEX)
    out["blocks"]["mandate"] = prompt.index(DIGEST_HEADER) - prompt.index(ANNEX)
    starts = [prompt.index(header) for header in (DIGEST_HEADER, EXCERPTS_HEADER,
                                                  COMMENTS_HEADER, SIGNALS_HEADER)]
    ends = starts[1:] + [chars]
    for name, start, end in zip(("sequences", "catalogue", "comments", "signals"), starts, ends):
        out["blocks"][name] = end - start
    return out


# ---- admission, as the proposer would meet it ---------------------------------------------
def _first_offer(stage, digest_arm):
    """The first observation the arm offers, as the arm's own proposal entry, and its path."""
    if digest_arm:
        from tokeneconomizer.knowledge.digest import citable
        for sequence in stage.digest.sequences:
            for unit in sequence["units"]:
                if not citable(unit):
                    continue
                symbol = sorted(unit.get("symbols") or {})[0] if unit.get("partial") else None
                entry = {"ref": unit["refs"][0]}
                if symbol:
                    entry["symbol"] = symbol
                return entry, unit["path"]
        return None, None
    for digest in stage.window:
        for source in digest.get("observed_sources") or ():
            record = (digest.get("_observations") or {}).get(source["path"]) or {}
            symbol = sorted(record.get("symbols") or {})[0] if record.get("partial") else None
            entry = {"source": source["path"]}
            if symbol:
                entry["symbol"] = symbol
            return entry, source["path"]
    return None, None


def _stale(stage, workspace, candidate, path, workdir):
    """Admit the same candidate against a copy of the workspace whose file has moved on: the
    real workspace is never touched, and the engine re-hashes what `stage.workspace` shows."""
    mirror = tempfile.mkdtemp(prefix="stale-", dir=workdir)
    relative = path if not os.path.isabs(path) else os.path.relpath(path, workspace)
    if relative.startswith(os.pardir):
        relative = os.path.basename(relative)
    target = os.path.join(mirror, relative)
    os.makedirs(os.path.dirname(target) or mirror, exist_ok=True)
    source = os.path.join(workspace, relative)
    if os.path.isfile(source):
        shutil.copyfile(source, target)
        with open(target, "ab") as handle:
            handle.write(b"\n# the file moved on\n")
    before = stage.workspace
    stage.workspace = mirror
    try:
        return stage._admit(dict(candidate, id="measure-stale"))[1]
    finally:
        stage.workspace = before
        shutil.rmtree(mirror, ignore_errors=True)


def _probe(stage, workspace, digest_arm, workdir):
    """What the arm's own admission answers for the first observation it offers: the candidate,
    the same claim a second time, and the same candidate after the file changed."""
    entry, path = _first_offer(stage, digest_arm)
    if entry is None:
        return {"entry": None, "reason": "no observation offered"}
    candidate = {"id": "measure", "claim": CLAIM, "sources": [entry], "detector": DETECTOR}
    admitted, reason = stage._admit(candidate)
    return {"entry": entry, "path": path, "admitted": admitted, "reason": reason,
            "duplicate": stage._admit(dict(candidate, id="measure-duplicate"))[1],
            "stale": _stale(stage, workspace, candidate, path, workdir)}


# ---- the control trace, for what the real logs do not exercise ----------------------------
CONTROL_WORKSPACE = "ws"
CONTROL_TRACE = "control.jsonl"


def write_control(directory, session="control"):
    """Generate the control trace in `directory` and return `(traces, workspace)`.

    Two work sequences, each of which meets the 16 000-character cap, because no real session on
    this machine did: the first keeps a 1 200-character read, stops at a 20 400-character one,
    and loses a 120-character one that would have fitted; the second opens with a 17 000-
    character read and keeps nothing. The files are what the log says they are, so the same fold
    also walks admission from `admitted` to `duplicate` to `stale-proof`. Two calls with distinct
    `session` names in one directory make a two-session window.
    """
    workspace = os.path.join(directory, CONTROL_WORKSPACE)
    os.makedirs(workspace, exist_ok=True)
    files = {"alpha.txt": _filler(10), "heavy.txt": _filler(102, width=200),
             "tiny.txt": _filler(1), "huge.txt": _filler(85, width=200)}
    for name, content in files.items():
        with open(os.path.join(workspace, name), "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
    turns = [["alpha.txt", "heavy.txt", "tiny.txt"], ["huge.txt"]]
    entries = [{"type": "session", "version": 3, "id": session, "cwd": workspace,
                "timestamp": "2026-01-01T00:00:00.000Z"}]
    parent, n = None, 0
    for index, names in enumerate(turns):
        stamp = f"2026-01-01T00:0{index}:00.000Z"
        prompt = {"type": "message", "id": f"m{n}", "parentId": parent, "timestamp": stamp,
                  "message": {"role": "user", "content": [
                      {"type": "text", "text": "read " + ", ".join(names)}]}}
        entries.append(prompt)
        parent, n = prompt["id"], n + 1
        for name in names:
            entries.append({"type": "message", "id": f"c{n}", "parentId": parent,
                            "timestamp": stamp, "message": {"role": "assistant", "content": [
                                {"type": "toolCall", "id": f"r{n}", "name": "read",
                                 "arguments": {"path": os.path.join(workspace, name)}}]}})
            entries.append({"type": "message", "id": f"t{n}", "parentId": f"c{n}",
                            "timestamp": stamp,
                            "message": {"role": "toolResult", "toolCallId": f"r{n}",
                                        "toolName": "read", "isError": False,
                                        "content": [{"type": "text",
                                                      "text": files[name]}]}})
            parent, n = f"t{n}", n + 1
    trace = os.path.join(directory, f"{CONTROL_TRACE[:-len('.jsonl')]}-{session}.jsonl")
    with open(trace, "w", encoding="utf-8") as handle:
        handle.write("\n".join(json.dumps(entry) for entry in entries) + "\n")
    return [trace], workspace


def _filler(lines, width=80):
    """Neutral, deterministic content of an exact size: `lines` lines of `width` characters."""
    return "".join((f"control line {number:03d} ".ljust(width, ".")[:width - 1] + "\n")
                   for number in range(1, lines + 1))


# ---- one arm -----------------------------------------------------------------------------
def measure(paths, workspace, label="current", keep_tmp=False):
    """Fold every trace of one arm through its own Knowledge stage, in this process, and return
    the report: per trace, what the fold put in front of the proposer and what admission said.

    The state lives in a temporary directory, so nothing reaches `~/.tokeneconomizer` and two
    runs start from the same empty state.
    """
    import tokeneconomizer
    from tokeneconomizer.knowledge.stage import workspace_id
    from tokeneconomizer.microskills import distiller
    from tokeneconomizer.plugin.config import load_config

    workspace = os.path.realpath(workspace)
    digest_arm = _digest_arm()
    # The fold rebinds the cadence from the configuration before it ticks; this harness does the
    # same, and passes `env={}` so an ambient TE_* variable cannot change the measurement.
    distiller.PROPOSE_EVERY = load_config(workspace, env={}).microskills_propose_every
    repo_id = workspace_id("measure", workspace)
    root = tempfile.mkdtemp(prefix="te-measure-state-")
    workdir = tempfile.mkdtemp(prefix="te-measure-trace-")
    try:
        records = [_fold(trace, workspace, root, repo_id, workdir, digest_arm)
                   for trace in traces_of(paths)]
        return {"arm": {"label": label, "digest": digest_arm,
                        "propose_every": distiller.PROPOSE_EVERY,
                        "package": os.path.dirname(os.path.dirname(
                            os.path.abspath(tokeneconomizer.__file__))),
                        **_budgets()},
                "workspace": workspace,
                "traces": records, "totals": _totals(records)}
    finally:
        if keep_tmp:
            print(f"kept {root} and {workdir}", file=sys.stderr)
        else:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(workdir, ignore_errors=True)


def _digest_arm():
    """Whether the arm under this interpreter is the work-sequence digest."""
    try:
        from tokeneconomizer.knowledge import digest  # noqa: F401
        return True
    except ImportError:
        return False


def _budgets():
    """The frozen values the report has to quote, read from the arm itself."""
    if not _digest_arm():
        return {}
    from tokeneconomizer.knowledge.digest import BUDGET, MESSAGE_CAP, PAIRS, SEQUENCES
    return {"sequences_budget": SEQUENCES, "sequence_char_budget": BUDGET,
            "message_char_cap": MESSAGE_CAP, "pairs_shown": PAIRS}


def _fold(trace, workspace, root, repo_id, workdir, digest_arm):
    """One session: the real fold, then a reading of what it produced, then the probes."""
    from tokeneconomizer.knowledge.stage import Knowledge
    from tokeneconomizer.microskills import distiller
    from tokeneconomizer.trace import pi_session_to_claude
    from tokeneconomizer.trace.pi import pi_prompt_count

    record = {"trace": trace, "session": _session_id(trace),
              **_trace_facts(_entries(trace), workspace)}
    try:
        record["prompts"] = pi_prompt_count(trace)
    except (OSError, ValueError):
        record["prompts"] = None
    converted = os.path.join(workdir, "pi_trace.jsonl")
    if pi_session_to_claude(trace, converted) is None:
        record["error"] = "unreadable trace"
        return record
    prompts = []

    def stub(prompt, model):
        prompts.append(prompt)
        return '{"facts": []}', 0

    stage = Knowledge.load(repo_id, root, runner=stub)
    stage.workspace, stage.host = workspace, "pi"
    before = _state(stage)
    # `update` folds the session and then ticks when the cadence is due -- with the stub as its
    # runner, so the prompt it would send is recorded and no model is called.
    due = before["sessions"] + 1 - before["last_propose"] >= distiller.PROPOSE_EVERY
    stage.update(converted, iid=record["session"], observed_transcript=trace, captures=None)
    record["tick"] = {"cadence": due, "sources": stage.has_proposal_sources(),
                      "ran": bool(prompts)}
    # A tick the cadence withheld still has a prompt: measure the digest's own volume either way.
    prompt = prompts[0] if prompts else stage._proposal_prompt()
    record["prompt"] = _prompt_metrics(prompt, digest_arm)
    record.update(_digest_metrics(stage, trace, workspace, record["session"]) if digest_arm
                  else _window_metrics(stage))
    stage.save(root)
    record["state"] = {"before": before, "after": _state(stage)}
    # The probes run on a copy of the saved state, so a candidate they admit never reaches the
    # next fold's prompt (the proposer is shown the claims it already holds).
    probe = Knowledge.load(repo_id, root)
    probe.workspace, probe.host = workspace, "pi"
    record["admission"] = _probe(probe, workspace, digest_arm, workdir)
    return record


def _state(stage):
    """The cadence counters a campaign report quotes: sessions folded, tick position, cost."""
    return {"sessions": stage.now, "last_propose": stage.last_propose,
            "opt_tokens": stage.opt_tokens}


# ---- the tables --------------------------------------------------------------------------
def _at(record, dotted):
    """A dotted key of a record, or None where the arm has no such metric."""
    value = record
    for key in dotted.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _totals(records):
    """Per-arm sums of every metric the arm has, plus the tick and admission tallies.

    `retention.*` counts this fold's own units, before and after its budget, so summing it says
    how much a campaign lost. `catalogue.*`, `window.*` and the prompt sizes are the state at
    that fold -- a sum is therefore "what one prompt held, added up over the folds".
    """
    totals = {key: sum(value for value in (_at(record, key) for record in records)
                       if isinstance(value, (int, float))) for key in SUMS}
    for key in MAXIMA:
        values = [value for value in (_at(record, key) for record in records)
                  if isinstance(value, (int, float))]
        if values:
            totals[key] = max(values)
    totals["ticks"] = {"cadence": sum(1 for r in records if _at(r, "tick.cadence")),
                       "sources": sum(1 for r in records if _at(r, "tick.sources")),
                       "ran": sum(1 for r in records if _at(r, "tick.ran"))}
    reasons = {}
    for record in records:
        reason = _at(record, "admission.reason") or "none"
        reasons[reason] = reasons.get(reason, 0) + 1
    totals["admission"] = dict(sorted(reasons.items()))
    return totals


def _short(trace, width=26):
    name = os.path.basename(trace)
    return name if len(name) <= width else name[:width - 1] + "\u2026"


_COLUMNS = {
    True: (("trace", 28), ("prompts", 8), ("reads", 6), ("paths", 6), ("seqs", 5), ("sess", 5),
           ("entr", 5), ("reps", 5), ("kept", 5), ("drop", 5), ("over", 5), ("chars", 9),
           ("tokens", 9), ("tick", 11), ("admit", 16)),
    False: (("trace", 28), ("prompts", 8), ("reads", 6), ("paths", 6), ("sess", 5), ("entr", 5),
            ("reps", 5), ("trunc", 6), ("chars", 9), ("tokens", 9), ("tick", 11),
            ("admit", 16)),
}
# The metric each column beyond `trace` reports, in column order, for the totals row.
_TOTAL_KEYS = {
    True: ("prompts", "reads", "paths", "digest.sequences", "digest.sessions",
           "digest.catalogue.entries", "digest.catalogue.repeated", "digest.retention.kept",
           "digest.retention.dropped", "digest.retention.overflow", "prompt.chars",
           "prompt.tokens"),
    False: ("prompts", "reads", "paths", "window.sessions", "window.entries",
            "window.repeated", "window.truncated", "prompt.chars", "prompt.tokens"),
}


def _flag(record):
    """Why the fold did or did not send a proposal call: `ran`, `cadence` (the tick was not
    due), `no-source` (nothing retained to propose from)."""
    tick = _at(record, "tick") or {}
    if tick.get("ran"):
        return "ran"
    return "cadence" if not tick.get("cadence") else "no-source"


def _cells(record, digest_arm):
    """One table row: the arm's metrics, `-` where the arm has none."""
    def cell(key, default="-"):
        value = _at(record, key)
        return default if value is None else value
    reason = (_at(record, "admission") or {}).get("reason", "-")
    if digest_arm:
        return [_short(record["trace"]), cell("prompts"), cell("reads"), cell("paths"),
                cell("digest.sequences"), cell("digest.sessions"),
                cell("digest.catalogue.entries"), cell("digest.catalogue.repeated"),
                cell("digest.retention.kept"), cell("digest.retention.dropped"),
                cell("digest.retention.overflow"), cell("prompt.chars"), cell("prompt.tokens"),
                _flag(record), reason]
    return [_short(record["trace"]), cell("prompts"), cell("reads"), cell("paths"),
            cell("window.sessions"), cell("window.entries"), cell("window.repeated"),
            cell("window.truncated"), cell("prompt.chars"), cell("prompt.tokens"),
            _flag(record), reason]


def print_arm(report):
    """One arm as a table, with its totals and its cadence counters beneath it."""
    digest_arm = report["arm"]["digest"]
    columns = _COLUMNS[digest_arm]
    totals = report["totals"]
    print(f"\n== {report['arm']['label']} arm "
          f"({'work-sequence digest' if digest_arm else 'per-session observed_sources'}) ==")
    print(f"   {report['arm']['package']}")
    print(f"   workspace {report['workspace']}, one proposal tick every "
          f"{report['arm']['propose_every']} session(s)")
    print("   " + "".join(name.ljust(width) for name, width in columns))
    for record in report["traces"]:
        print("   " + "".join(str(cell).ljust(width) for cell, (_name, width)
                              in zip(_cells(record, digest_arm), columns)))
    sent = f"{totals['ticks']['ran']}"
    print("   " + "total".ljust(28) + "".join(
        str(totals.get(key, "-")).ljust(width) for key, (_name, width)
        in zip(_TOTAL_KEYS[digest_arm], columns[1:])) + sent.ljust(11)
          + str(totals["admission"]).ljust(16))
    print(f"   proposal ticks (cadence due / sources offered / sent): "
          f"{totals['ticks']['cadence']} / {totals['ticks']['sources']} / "
          f"{totals['ticks']['ran']}")
    print(f"   admission of the first offered observation: {totals['admission']}")
    if "digest.retention.max_used" in totals:
        print(f"   retention: {totals['digest.retention.dropped']} unit(s) dropped by a budget "
              f"({totals['digest.retention.dropped_chars']} chars refused), "
              f"{totals['digest.retention.overflow']} sequence(s) stopped before their last "
              f"unit, fullest sequence {totals['digest.retention.max_used']} chars "
              f"of {report['arm'].get('sequence_char_budget', '-')}")
        print(f"   window: {totals['digest.retention.windowed_out']} sequence(s) of their own "
              f"session pushed out ({totals['digest.retention.windowed_units']} unit(s)) by the "
              f"{report['arm'].get('sequences_budget', '-')} slots")
    if "window.truncated" in totals:
        print(f"   excerpts: {totals['window.truncated']} record(s) cut at 2 000 chars, "
              f"{totals['window.excerpt_chars']} chars shown of "
              f"{totals['window.content_chars']} observed")


_COMPARED = (("prompts in the traces", "prompts", "prompts", False),
             ("read calls in the traces", "reads", "reads", False),
             ("distinct paths read", "paths", "paths", False),
             ("observations offered", "digest.catalogue.entries", "window.entries", True),
             ("distinct paths offered", "digest.catalogue.paths", "window.paths", False),
             ("repeated path offered", "digest.catalogue.repeated", "window.repeated", False),
             ("prompt characters", "prompt.chars", "prompt.chars", True),
             ("prompt tokens (chars/4)", "prompt.tokens", "prompt.tokens", True),
             ("observation characters", "observation_chars", "observation_chars", True),
             ("sequences over the cap", "digest.retention.overflow", None, False),
             ("sequences pushed out of the window", "digest.retention.windowed_out", None,
              False),
             ("observations cut at 2 000", None, "window.truncated", False),
             ("proposal ticks sent", "ticks.ran", "ticks.ran", False))


def compare(current, baseline):
    """The two arms side by side on the metrics both arms have, with their difference.

    Window-wide metrics are summed over the folds and, where a per-fold reading means more, also
    averaged: the totals say how much a campaign paid, the average how large one proposal prompt
    was.
    """
    folds = len(current["traces"]) or 1
    rows = []
    for name, left, right, per_fold in _COMPARED:
        mine = _total(current["totals"], left) if left else None
        theirs = _total(baseline["totals"], right) if right else None
        rows.append({"metric": name, "current": mine, "baseline": theirs,
                     "delta": None if mine is None or theirs is None else mine - theirs})
        if per_fold and mine is not None and theirs is not None:
            rows.append({"metric": name + " / fold", "current": round(mine / folds, 1),
                         "baseline": round(theirs / folds, 1),
                         "delta": round((mine - theirs) / folds, 1)})
    print("\n== comparison on the same traces ==")
    print("   " + "metric".ljust(30) + "current".rjust(10) + "baseline".rjust(10)
          + "delta".rjust(10))
    for row in rows:
        print("   " + row["metric"].ljust(30)
              + str(row["current"] if row["current"] is not None else "-").rjust(10)
              + str(row["baseline"] if row["baseline"] is not None else "-").rjust(10)
              + (str(row["delta"]) if row["delta"] is not None else "-").rjust(10))
    for report in (current, baseline):
        print(f"   {report['arm']['label']:<10} ticks {report['totals']['ticks']} "
              f"admission {report['totals']['admission']}")
    return rows


def _total(totals, key):
    """One metric of the totals, including the tick tallies."""
    if key == "ticks.ran":
        return totals["ticks"]["ran"]
    return totals.get(key)


# ---- the two arms, in their own processes ------------------------------------------------
def _run_arm(label, repo, pythonpath, traces, workspace, workdir, keep_tmp):
    """Measure one arm in a subprocess whose `tokeneconomizer` is the arm's own."""
    out = os.path.join(workdir, f"{label}.json")
    command = [sys.executable, os.path.abspath(__file__), "--arm", label,
               "--repo", repo, "--workspace", workspace, "--out", out,
               "--traces", *traces]
    env = dict(os.environ, PYTHONPATH=pythonpath)
    if keep_tmp:
        command.append("--keep-tmp")
    done = subprocess.run(command, env=env, cwd=workdir, capture_output=True, text=True,
                          encoding="utf-8")
    if done.returncode != 0:
        raise SystemExit(f"{label} arm failed ({done.returncode}):\n{done.stderr}")
    sys.stdout.write(done.stdout)
    with open(out, encoding="utf-8") as handle:
        return json.load(handle)


def _materialise(ref, repo, workdir):
    """The baseline arm's tree at `ref`, outside the repository, with no git state left over."""
    root = os.path.join(workdir, "baseline")
    os.makedirs(root)
    archive = subprocess.run(["git", "-C", repo, "archive", ref], capture_output=True)
    if archive.returncode != 0:
        raise SystemExit(f"git archive {ref} failed:\n{archive.stderr.decode()}")
    tar = subprocess.run(["tar", "-x", "-C", root], input=archive.stdout)
    if tar.returncode != 0:
        raise SystemExit(f"could not extract {ref}")
    return root


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--traces", nargs="+",
                        help="Pi session logs, or directories of them")
    parser.add_argument("--workspace", default=os.getcwd(),
                        help="the workspace the reads are proved against")
    parser.add_argument("--control", metavar="DIR",
                        help="write the control trace into DIR and measure it instead of "
                             "--traces")
    parser.add_argument("--baseline-ref", default="f1a6c18",
                        help="the commit whose Knowledge digest is the left-hand side")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="where to write the JSON report (a temporary path by default)")
    parser.add_argument("--limit", type=int, help="measure at most this many traces")
    parser.add_argument("--arm", help="measure only this arm in this process (internal)")
    parser.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(
        __file__))), help="the repository `--baseline-ref` is read from")
    parser.add_argument("--keep-tmp", action="store_true", help="keep the temporary directories")
    args = parser.parse_args(argv)
    if args.control:
        os.makedirs(args.control, exist_ok=True)
        traces, workspace = write_control(args.control)
    elif args.traces:
        traces, workspace = traces_of(args.traces, args.limit), args.workspace
    else:
        raise SystemExit("give --traces or --control")
    if not traces:
        raise SystemExit("no trace found")
    out = _outside_repository(args.out, args.repo)
    if args.arm:
        report = measure(traces, workspace, args.arm, keep_tmp=args.keep_tmp)
        print_arm(report)
        _write(out, report)
        return 0
    workdir = tempfile.mkdtemp(prefix="te-measure-")
    try:
        baseline_root = _materialise(args.baseline_ref, args.repo, workdir)
        current = _run_arm("current", args.repo, args.repo, traces, workspace, workdir,
                           args.keep_tmp)
        baseline = _run_arm("baseline", args.repo, baseline_root, traces, workspace,
                            workdir, args.keep_tmp)
        rows = compare(current, baseline)
        report = {"arms": {"current": current, "baseline": baseline},
                  "baseline_ref": args.baseline_ref, "comparison": rows}
        _write(out, report)
        return 0
    finally:
        if args.keep_tmp:
            print(f"kept {workdir}", file=sys.stderr)
        else:
            shutil.rmtree(workdir, ignore_errors=True)


def _outside_repository(path, repo):
    """`path` itself when it lies outside the checkout, else the temporary default: a
    measurement must not leave its JSON inside the repository."""
    full, root = os.path.realpath(path), os.path.realpath(repo)
    try:
        inside = os.path.commonpath([root, full]) == root
    except ValueError:            # different drives on Windows
        inside = False
    if not inside:
        return path
    print(f"{path} is inside the repository; writing {DEFAULT_OUT} instead", file=sys.stderr)
    return DEFAULT_OUT


def _write(path, report):
    if not path:
        return
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1, ensure_ascii=False, sort_keys=False)
        handle.write("\n")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    sys.exit(main())
