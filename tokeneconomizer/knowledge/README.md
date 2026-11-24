# File-backed Knowledge

Knowledge is experimental and off by default. Set `knowledge=on` with `te config set`
or `TE_KNOWLEDGE=on` to enable it independently of the native mechanisms. It currently
accepts:

- Claude Code `Read` results with complete-file metadata and matching model-visible content;
- Pi `read` results on the active session branch. A complete file read must carry no
  truncation details or notices; a read of part of a file (`offset` and/or `limit`) counts only
  when the PostToolUse hook kept the file's bytes immediately after the read returned, and the
  logged result -- the body plus the line total its footer declares -- still matches those
  bytes, footer included. An edit inside the read's window between the read and the capture
  fails closed; an edit outside that window is caught only when it changes the line count the
  footer declares. This adapter was checked against the locally installed Pi 1.2.0, and the
  result formats against Pi 1.6.0;
- Copilot `view` file results from session format version 1.0.105, without a range or avoided
  large output, with telemetry confirming that the whole result reached the model. Files at or
  above 20 KiB and sessions without the required telemetry are rejected conservatively.

Failed, lossy, transformed and unverifiable reads are ignored, as is a partial read whose
capture is missing or no longer describes the file. Captures are kept per Pi session (at most
12 files and 8 MiB, expiring after 7 days) and removed after the session is folded: each one
holds the file's bytes, bounded, only until then. They live under
`knowledge_captures/<session>-<digest>/` in the store: an `index.json` and one `<sha256>.bin`
per capture, whose content is checked against its name on load. Treat that name and layout as a
compatibility surface. Several partial reads of one file add up only when they were captured on
the same version of the file; after a change in between, the later read stands alone. The captured file itself is never stored in
the observation or in the persisted Knowledge state, where only the excerpt the model received
appears. Other hosts, Copilot versions and read formats do not yet supply evidence. The Pi and
Copilot test fixtures are sanitized local sessions recorded with a simulated model provider;
their file paths and Pi system prompt were replaced, while the tool calls and results were
retained.

The proposer sees bounded excerpts of observed reads -- complete ones, and partial ones with
the lines they returned (`observed_lines`) -- and identifies a source and session. A partial
read that crossed no declaration has nothing to prove, so it is not offered at all. It runs
on the existing micro-skills proposal cadence and uses TE's grounding, confirmation,
contradiction and firing thresholds. The proposal is a separate model call;
verification is local and makes no model call. Knowledge shares the configured micro-skills
injection limits with native facts (what the native facts injected at session start counts
against them). State is isolated by workspace path. `te microskills`
lists Knowledge identity, revision, lifecycle, proof status, source session and path, and the
lines a partial read actually returned, including forgotten records. Use
`te microskills forget ID` to suppress one and `te microskills unforget ID` to restore its
saved lifecycle; injection still requires a valid proof and the usual lifecycle gates.

## When Knowledge is injected

Knowledge is injected only when it is Relevant Knowledge, and never at session start. A
Knowledge Signal is the symbol the Knowledge's contract names or, failing that, its file. The
user prompt hook injects a Knowledge when the request names its symbol (as a whole identifier)
or its file (by path or file name, in any case; `source.txt` is not matched inside
`resource.txt` or `source.txt.bak`). Matching is local and deterministic, with no model call.
A request that shares no signal injects nothing. Stored Knowledge needs no migration: its
signal comes from its current contract. A composed Knowledge has no signal of its own and is
relevant when a signal of any Knowledge it is pinned to matches.

Native facts still arrive at session start. A host whose hook output does not reach the model
(`prompt_context` false: Codex, Cursor, Antigravity, Grok) gets no Knowledge, and neither does
one whose plugin can only put prompt context in its system prompt (`prompt_knowledge` false:
opencode), because a text that varies by prompt would rewrite the cached prefix of every later
request. The Knowledge goes where the host puts a prompt's context, after the cached prefix;
on Pi, whose extension re-sends a system-prompt section on every prompt, it is a message after
the prompt (`promptMessage` in the dispatcher's answer), not part of that section. A selection
error leaves the hook's output empty.

A Knowledge is injected once per session: its id is kept in the session state
(`knowledge_given`, separate from the native `injected_ids`), and later prompts naming the same
signal inject nothing new. A clear, a compact or a new session drops the context and empties
that memory, so the Knowledge can be injected again. A resumed session on a host that replays
its context (Claude Code) keeps it and is not injected twice; a host that rebuilds a resumed
conversation without what its start added (Copilot, `keeps_start_context` false) also empties
it, as the native facts are re-sent there, so the Knowledge returns at the next relevant prompt.
When more Knowledge matches than the shared budget holds, the strongest match is kept first.
Strength of match is: a symbol named as a whole identifier (3), then a file named by its full
path (2), then a file named by its bare file name (1); a composed Knowledge counts its strongest
matching signal. Equal matches are ordered by firing rate, highest first, and what still ties
keeps registration order, so the choice is deterministic and makes no model call.

Each Knowledge actually injected is logged, one line per Knowledge, in the repository's
`events.jsonl` (the log of the native `inject` events) as `kind: "knowledge"` with
`knowledge_id`, `signal` (the symbol or file the prompt named), `trigger` (`"prompt"`), plus
the usual `at`, `session_id` and `shadow`. Nothing is logged when nothing is injected, and
forgotten, stale-proof or budget-dropped Knowledge never appears. Other triggers add fields to
this event rather than a new kind.

Before each new injection TE hashes the current file and drops only Knowledge whose proof
no longer matches. Deletion and read errors fail closed; restoring the exact bytes restores
eligibility subject to the lifecycle. A revised Knowledge retains its identity but must earn
new confirmations. Earlier context in a conversation cannot be removed retroactively. Knowledge is untrusted data: a matching hash does not establish that
the explanation is correct.

## Symbol contracts

The optional `symbol` proposal field names one unqualified declaration the observation
supports. Tree-sitter must parse the file without errors and resolve the name uniquely. The
contract hashes the declaration's non-comment tokens, including decorators; changes elsewhere
and comment-only changes do not invalidate it.

For a complete observed source, a symbol that cannot be resolved produces a file proof with a
recorded fallback reason and requested symbol. A partial read has no such fallback: it proves
the whole declaration its lines crossed, in the version captured at read time, so Knowledge
from it must name one of those declarations; a missing symbol, a name the read did not cross,
or a declaration that has changed since the read is refused instead of falling back to the
file. Existing symbol proofs fail closed if the grammar, parser, or recorded version is
unavailable or changes. The CLI's `te microskills` output lists the extensions whose parsers
can currently load; supported declaration forms are limited to those recognized by Knowledge.
Install the package dependencies to enable symbol parsing.


The proposer can synthesize two or more distinct existing atomic Knowledge entries.
TE resolves their IDs to current revisions while holding the mechanisms lock, and
the synthesis follows the same lifecycle and selection budget. Before every new
injection, each dependency must still exist at its pinned revision, be eligible,
and have a valid proof. Forgetting, revising, or invalidating a dependency excludes
the synthesis without deleting it; atomics remain independently usable. Nested
syntheses are not supported. Inspection displays the pinned dependencies.

## Recorded-session evaluation

`tests/test_knowledge_pi.py::test_pi_hook_learns_from_recorded_active_sessions`
replays the sanitized Pi complete-read recording five times through the live hooks,
with distinct session IDs, an added simulated successful `pytest` command, and a
stub proposer returning one grounded file candidate. No lifecycle threshold or
proposal cadence is overridden. The following counts are `(stored, eligible for
rendering)` after each fold: `(0, 0), (1, 0), (1, 0), (1, 1), (1, 1)`.
The test also checks the hook output, forget/unforget, deletion and restoration.
The separate Copilot recording test exercises a second host. Workflow tests cover
file and symbol contracts, compositions, revision, warm-cache revalidation,
workspace isolation, budget, native coexistence and user controls.

This is a deterministic integration scenario, not a representative yield estimate:
the same read is replayed, confirmations are synthetic and the candidate is supplied
by a stub rather than a real model. It does not measure real-world proposal quality,
latency, token savings or cost. Proof validity does not establish semantic truth.
Already-injected context cannot be retracted from a conversation.

## Upstream maintenance surface

The local baseline `e7cc7598bd013bf71011ae49c27f6c3e14c22ac4` is the fork's
`main` at evaluation time; no upstream remote-tracking ref was available locally,
so this is a baseline comparison, not a claim about current upstream HEAD. Before
this evaluation change, the branch differs by 26 files, 1,187 insertions and 19
deletions. Most additions are the isolated `knowledge` package and tests/fixtures;
shared changes touch configuration, fold and controller hooks, CLI inspection,
selection budget, packaging dependencies and the micro-skills stage. Future rebases
must recheck these seams, host transcript formats and the optional Tree-sitter pack.
No performance improvement is assumed.
