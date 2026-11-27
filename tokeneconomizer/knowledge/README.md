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
the lines they returned (`observed_lines`) -- each under the digest of the session that made
it. A partial read that crossed no declaration has nothing to prove, so it is not offered at
all. A Knowledge proposal names what it observed in `sources`, one or more
`{source, symbol?, source_session?}` entries; the engine resolves each entry against the
window's observations and computes the proofs itself, so the proposal never carries one. A
source observed in several sessions of the window must name its `source_session`. Several
sources may support one mechanism, but one complete read -- or one symbol a partial read
crossed -- is enough. It runs on the existing micro-skills proposal cadence, but not on the
native grounding gate: the proofs are the evidence, so a Knowledge is admitted and injectable
in the same cycle, with no second session and no confirmation count. When the native proposer
is active and at least one source is observed, one model call proposes up to eight candidates
in any mix. The fold ledger records proposal and admission counts by type under
`injection.shared_proposals`. Verification is local.
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
`detector` -- and the `sources` it observed in its proposal: one or more
`{source, symbol?, source_session?}` entries. The engine resolves each entry against the
window's observations, refuses one that no observation backs (`source-not-observed`), one the
window observed in more than one session without an explicit `source_session`
(`ambiguous-source`), a partial read without a symbol (`partial-needs-symbol`), a symbol the
read did not cross (`symbol-not-observed`), and a proof that no longer verifies
(`stale-proof`); two entries that resolve to the same file are one source, not two. The
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
