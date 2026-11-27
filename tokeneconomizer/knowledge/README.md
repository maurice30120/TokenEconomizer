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

What the proposer reads is a digest of **work sequences**: one per real user message, taken
from the eight newest messages by emission time across every session folded so far, so a
session folded late with older prompts lands where its times put it and two prompts of one
session are two sequences. A message that read nothing still takes its slot; an injected
message (Pi's extension sends its steering that way) and a `system` message open none. A
sequence keeps its message, bounded, and what each of its reads observed -- the code as the
read returned it, in read order -- up to 16 000 characters; the first observation that would
push it past that ends its retention, and every sequence has its own budget. Reads are
consolidated before that budget applies: two reads are the same code when the whole-file
version they observed is the same, so a repeated read is charged and shown once.

A sequence also keeps what the agent itself wrote: the visible `text` blocks of its assistant
messages, attached to the reads of the call series they followed. A reply's text joins the
series whose results are already there, and then that reply's own tool calls close the series --
so the text Pi writes beside the next call still belongs to the reads before it, which is how a
Pi session becomes readable at all, and a comment written after that next series returned
attaches to nothing. A series that returned no read owns nothing, and a user message ends the
window: nothing attaches backwards across it. A comment costs its text in the same 16 000
characters as the code it is about, so a comment that does not fit ends the sequence's retention
together with the read it was attached to, and a comment about a read the budget dropped is
neither shown nor citable. Identical comments are one entry,
oldest first, keeping their occurrences, the refs they are about and their provenance
(session, sequence, position). They cost neither a model call nor a tool call: they come from
the transcript the fold already reads. Pi assistant messages and Claude Code assistant
`text` blocks are the sources; Copilot has no assistant-message reader, so its sequences
carry no comments and none is invented.

The proposer reads a catalogue of that retained code, one entry per path and compatible
version, in first-appearance order: an entry lists every `ref` that hit it, in read order,
with the work sequence and session each ref names, and how many reads, sequences and sessions
it stands for. Ranges of one version merge when they overlap, a complete read subsumes the
partial reads of that version, and fragments that do not touch stay separate `fragments` of
the entry, each with its own lines, its crossed declarations and its refs. Another version is
another entry, even when a line shift leaves a declaration's own fingerprint identical: the
whole-file version, never the symbol hash, is what says two reads saw the same code. A partial
entry answers only for the declarations its lines crossed, so no entry becomes citable for
code it did not keep, and a partial read that crossed no declaration is neither shown nor
citable.

The prompt also shows the counts of reads, work sequences and sessions, and the pairs of
paths read in the same work sequence with how many sequences show each pair. Those pairs are
signals only -- converging explorations worth a look -- never evidence: two files read
together say nothing about a functional relation, recurrence is not proof, and no code path
admits a proposal from one.

The agent's comments are shown next to the refs they are about, labelled untrusted data, and
the contract tells the proposer to keep a finding (what the retained code shows), a hypothesis
(what the agent guessed) and a future requirement (what a request or a note expects and the
code does not do yet) apart: a comment, or a spec that is not implemented, never establishes a
Knowledge on its own, because only the retained code observations are proof.

A Knowledge proposal names what it observed in `sources`, one or more
`{ref, symbol?}` entries, and the engine resolves each ref against the retained digest and
computes the proofs itself, so the proposal never carries one. Several refs may support one
mechanism, but one complete read -- or one symbol a partial read crossed -- is enough. It runs
on the existing micro-skills proposal cadence, but not on the native grounding gate: the
proofs are the evidence, so a Knowledge is admitted and injectable in the same cycle, with no
second session and no confirmation count. When the native proposer is active and at least one
observation is retained, one model call proposes up to eight candidates in any mix. The fold
ledger records proposal and admission counts by type under `injection.shared_proposals`.
Verification is local. A session is folded once, so messages a resumed session appends never
re-enter the digest.
State is isolated by workspace path. `te microskills`
lists Knowledge identity, revision, lifecycle, proof status, source session and path, and the
lines a partial read actually returned, including forgotten records. Use
`te microskills forget ID` to suppress one and `te microskills unforget ID` to restore its
saved lifecycle; injection still requires a valid proof and an unretired lifecycle.

## When Knowledge is injected

On Pi and Copilot CLI, the session-start hook can give eligible Knowledge alongside native
facts, ordered by firing rate and then registration order. Both hosts can also deliver Relevant
Knowledge after a successful read of any covered file. Hosts that support the earlier prompt
trigger keep it, while Pi and Copilot use startup and read triggers for this experiment.
Stored Knowledge is read in one format only: the engine's proofs and provenance, with no
compatibility reader and no migration, so an old-format state file is simply absent.

A Knowledge card is the injection line the proposer wrote: one sentence about the mechanism.
The engine keeps the sources and their proofs out of the injected text.
Knowledge has a total budget for the conversation context. Set `knowledge_max_cards` (default
4), `knowledge_max_tokens` (default 300 estimated tokens) and `knowledge_startup_share`
(default 0.5, from 0 to 1) via the regular `te config` settings. The startup share applies to
both limits, rounded down. At 0, Knowledge only arrives after a read on Pi and Copilot. Unused
startup capacity is available later. Native facts use their own budget. A map must fit in full.

An already delivered card consumes its allowance only once while it remains in context.
Duplicate start hooks for the same event are ignored for both native facts and Knowledge.
Copilot rebuilds start context on resume, so TE restores the original eligible card revisions
without charging again. A clear or a compaction that drops Knowledge frees its capacity. Pi
compaction keeps the startup section and the steer messages still in the retained history.

### The prompt trigger

The user prompt hook injects a Knowledge when the request names its signal: the symbol as a
whole identifier (`target` matches, `retarget` does not), or its file by path or by file name,
in any case (`source.txt` is not matched inside `resource.txt` or `source.txt.bak`). It runs on
`UserPromptSubmit`, with `knowledge=on`, also when the loop guard is off, and only on a host
whose prompt output reaches the model (`prompt_context`) and can carry a text that varies by
prompt without rewriting the cached prefix (`prompt_knowledge`). That is Claude Code,
Droid and Hermes; opencode gets none, because its plugin
can only write the system prompt; Codex, Cursor, Antigravity and Grok get none, because their
prompt hook's output reaches no model. A shadow run and a replayed (queued) hook inject
nothing from this trigger.

When more Knowledge matches a prompt than the remaining Knowledge budget holds, the strongest match is kept
first: a symbol named as a whole identifier (3), then a file named by its full path (2), then a
file named by its bare file name (1); a Knowledge with several sources counts its strongest
matching signal. Equal matches are ordered by firing rate, highest first, and what still ties
keeps registration order, so the choice is deterministic and makes no model call.

Delivery is the host's own prompt context, after what the cached prefix holds.

### The read trigger

The second trigger is the agent reading a file a Knowledge covers (any of the
files it is about), even when the request never named it. It
runs on `PostToolUse` after a file-reading tool (`Read`, `read`, `view`) succeeds, with
`knowledge=on`, also when the loop guard is off, and only on a host verified to put that
context after the tool's result at the end of the conversation (`tool_context`: Claude Code,
Copilot, Pi). A host not verified gets nothing from this trigger. The same once-per-session
memory (`knowledge_given`) and the same budget, proof, lifecycle and forgotten gates apply. A
Knowledge already given in the context is skipped. The file must lie
inside the workspace. Every match is an exact path, so covering Knowledge is ordered by firing rate, then
registration order. A subagent's read, a failed
read, a shadow run and a replayed (queued) hook inject nothing.

**The read trigger cannot save its own read.** It injects only after the tool result
(`when: "after_read"`). A card delivered at startup can already be in context at that point.
The session state remembers the files read (`files_read`, emptied with
`knowledge_given`), so the log says when the file had been read earlier in the session
(`read_before`): then the Knowledge came too late for that read as well. The reads are
remembered whenever the host reports one, also where it cannot inject after a read. Reads are
recognized by tool name (`Read`, `read`, `view`); a host with another name for it reports none.

#### Verified hosts: hook before the tool call (probe, 2026-11-24)

Each host ran a scripted OpenAI-compatible endpoint on localhost that read two files, in an
isolated config directory (`COPILOT_HOME`, `PI_CODING_AGENT_DIR`), with a throwaway hook or
extension that emitted a canary string; the requests the model would have received were
recorded, so no real model was involved.

| Host | Accepts context before the call | Tool denied | Seen before the result | Prefix of the next request |
|---|---|---|---|---|
| Copilot CLI 1.0.114 (`PreToolUse`, top-level or `hookSpecificOutput` `additionalContext`) | yes | no | **no**: a user message *after* the tool result ("Additional context from preToolUse hook") | unchanged |
| Pi 1.6.0 (`tool_call`) | **no**: it can only block or edit the input; a message sent from it (`sendMessage`, steer) lands after the result | no | **no** | unchanged |

Result: neither host can inject before the read, so no pre-read injection exists; both use the
fallback below.

#### Verified hosts: context after the tool call (`PostToolUse`)

| Host | Delivery | Placement | Prefix of the next request |
|---|---|---|---|
| Copilot CLI 1.0.114 | top-level `additionalContext` | appended to the tool result ("Additional guidance from postToolUse hooks") | unchanged, system prompt and tools identical |
| Pi 1.6.0 | the extension's steering message (`additionalContext` of the answer) | a user message after the result | unchanged |
| Claude Code | `hookSpecificOutput.additionalContext`, followed in the same turn (`docs/PLUGIN.md`, earlier verification) | after the result | not re-probed here; context goes to the end of the conversation |

Not verified for this trigger, so nothing is injected: Codex (it reads through the shell, with no
file-reading tool), Cursor, Antigravity, Grok, Droid, opencode, Hermes.

Each Knowledge actually injected is logged, one line per Knowledge, in the repository's
`events.jsonl` (the log of the native `inject` events) as `kind: "knowledge"` with
`knowledge_id`, `signal` (the symbol or file the prompt named, or the file that was read),
`trigger` (`"startup"`, `"prompt"` or `"read"`), plus the usual `at`, `session_id` and `shadow`. A read
adds `when` (`"after_read"`). Both triggers add `read_before`: on a read, the file had been read
earlier in the session; on a prompt, one of the Knowledge's own files had been. Nothing is logged when nothing is injected, and
forgotten, stale-proof or budget-dropped Knowledge never appears. The triggers share this one kind; the ledger has no
`injection` field for Knowledge, which belongs to the paid optimizer.

Before each new injection TE hashes the current file and drops only Knowledge whose proof
no longer matches. Deletion and read errors fail closed; restoring the exact bytes restores
eligibility subject to the lifecycle. A revised Knowledge keeps its identity, replaces its
stored claim, injection, detector and contract at once, and needs no new confirmation; a
contradiction still retires it. Earlier context in a conversation cannot be removed
retroactively. Knowledge is untrusted data: a matching hash does not establish that
the explanation is correct.

## What Copilot lets TokenEconomizer observe and prove

Copilot CLI gives Knowledge less than Pi and Claude Code, and the gap is in what the host
records, not in a missing parser. The refusing predicates live in
`knowledge/observation.py::_copilot_observations`; each limit below has a test in
`tests/test_knowledge_copilot.py`.

- **One session format only.** A tool result is read only when
  `session.start.context.copilotVersion` is exactly `1.0.105`. Any other version yields no
  observation at all, so a Copilot upgrade stops Knowledge learning silently instead of
  degrading it.
- **Truncation telemetry is mandatory.** The result must carry
  `toolTelemetry.properties` with `viewType: "file"`, `command: "view"`, no
  `largeOutputAvoided`, `options` exactly
  `{"truncateBasedOn":"tokenCount","truncateStyle":"middle"}` and `inputs` exactly
  `["path", "command"]`, and `metrics.resultLength` and `resultForLlmLength` must both equal
  the UTF-16 length of the content. Without it TE cannot tell a whole file from a truncated
  `view`, so a session that does not log it proves nothing.
- **A 20 KiB ceiling.** A result at or above 20 480 bytes, or one flagged
  `largeOutputAvoided`, is refused. The agent can still read a 40 KiB file; TE can never prove
  what it read there.
- **No partial `view`.** `arguments` must be exactly `{"path"}`: a `view_range` is refused
  outright, and there is no capture path for Copilot (`knowledge/capture.py` is Pi-only). So
  Copilot produces no line ranges and no fragments, and **no symbol proof from a partial
  read**: `partial-needs-symbol` and `symbol-not-observed` are unreachable there, because the
  partial reading they guard can never be observed.
- **No agent comments.** No `assistant.message` event is parsed, so a Copilot sequence carries
  no visible comments and none is invented.
- **No prompt text and no timestamp in any proof.** The bounded `user.message` text is a
  sequence's context and `data.turnId` is unread; a read is placed against its sequence by
  event position, never by comparing times, and no prompt text ever reaches a proof.
- **One bad line loses the session.** The strict UTF-8/JSON reader fails closed, so a recording
  with a corrupted tail yields no observation.

Pi and Claude Code are not symmetric with each other either, but they give more: Pi attests a
partial `read` through the bytes its hook captured (so it does prove a declaration the read
crossed), and both expose the agent's own `text` blocks, which Copilot does not. What each of the
two digests costs on real Pi session logs is measured in `rapport-campagne-341.md`, at the root of
the workspace this repository is checked out in (TokenEconomizer keeps no run outputs in git).

## Measuring the digest on Pi session logs

`scripts/knowledge_digest_measure.py` folds a directory of Pi `*.jsonl` session logs through the
real Knowledge stage -- `Knowledge.load` then `update`, with the host's own conversion for the
digest, the raw log for the observations and no captures -- with a stub proposer that records the
prompt and answers `{"facts": []}`. No model is called, no network is used and no clock is read.

```
PYTHONPATH=$PWD python scripts/knowledge_digest_measure.py \
    --traces <dir-of-pi-jsonl> --workspace <the repo those reads happened in>
```

It measures two arms on the same traces: this tree, and `--baseline-ref` (default `f1a6c18`, the
integration tip before the work-sequence digest) materialised with `git archive` in a temporary
directory outside the checkout. Each arm runs in its own subprocess, because both export the same
module names. Per fold it writes, as JSON and as a table, the prompt's size and its per-block split,
the sequences, catalogue entries and reads the digest offered, the units its budget dropped, whether
the proposal tick was due and whether it fired, and what admission answers for a minimal candidate
built from the first observation offered -- the candidate itself, the same claim twice
(`duplicate`), and the same candidate after the file changed (`stale-proof`, probed against a copy:
the real workspace is never touched). `--control <dir>` writes and measures a synthetic witness for
the cases real logs do not exercise; `--arm current` skips the baseline. The JSON goes to `--out`,
which defaults to a temporary file outside the checkout. State lives in temporary directories, so
`~/.tokeneconomizer` is never written. `tests/test_knowledge_digest_measure.py` pins the report's
shape, the cadence, the two-session window and the determinism.

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


A new or revised Knowledge carries the four business fields -- `id`, `claim`, `injection`,
`detector` -- and the `sources` it observed in its proposal: one or more `{ref, symbol?}`
entries. The engine resolves each ref against the observations the digest retains, and refuses
one it does not show -- unknown, ambiguous, dropped by a sequence's budget, or never citable
(`out-of-digest`) -- a partial read without a symbol (`partial-needs-symbol`), a symbol the
read did not cross (`symbol-not-observed`), and a proof that no longer verifies
(`stale-proof`); two refs that resolve to the same file are one source, not two. The
stored spec keeps only the business fields, the revision, and the engine's own `proof` list
and `provenance` -- never the proposal's entries. One complete read, or one symbol a partial
read crossed, is enough; several sources are allowed when they explain one mechanism, and the
Knowledge is valid only while every proof is. Inspection lists all its sources. Knowledge that
synthesizes other Knowledge is not supported; a stored one of that kind has no proof, so it is
never injected.
Admission also rejects explicit workspace-relative file references in the claim or the
injection that resolve to existing files outside its sources. This check does not resolve
every shorthand or implied reference and does not prove the explanation is correct.

## Recorded-session evaluation

`tests/test_knowledge_pi.py::test_pi_hook_learns_from_recorded_active_sessions`
replays the sanitized Pi complete-read recording five times through the live hooks,
with distinct session IDs, an added simulated successful `pytest` command, and a
stub proposer returning one grounded file candidate. No lifecycle threshold or
proposal cadence is overridden. The following counts are `(stored, eligible for
rendering)` after each fold: `(0, 0), (1, 1), (1, 1), (1, 1), (1, 1)`.
The test also checks the hook output, forget/unforget, deletion and restoration.
The separate Copilot recording test exercises a second host. Workflow tests cover
file and symbol contracts, several sources, revision, warm-cache revalidation,
workspace isolation, budget, native coexistence and user controls.

This is a deterministic integration scenario, not a representative yield estimate:
the same read is replayed, the candidate and its proof are supplied by a stub rather
than a real model. It does not measure real-world proposal quality,
latency, token savings or cost. Proof validity does not establish semantic truth.
Already-injected context cannot be retracted from a conversation.

`rapport-campagne-341.md`, at the root of the workspace this repository is checked out in, is the
measurement this paragraph is not: it replays real Pi session logs through the work-sequence digest
and through the `observed_sources` view it replaced, and reports the volume each puts in front of
the proposer, what the 16 000-character budget dropped, and how often admission was reachable. Its
harness is `scripts/knowledge_digest_measure.py` (see above); the frozen values it reports on (8
sequences, 16 000 characters) are the initial calibration, not a tuned result.

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
