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
together with the file the symbol lives in, or its file when the contract has no symbol (by path
or file name, in any case; `source.txt` is not matched inside `resource.txt` or
`source.txt.bak`). A symbol alone is not enough: a name such as `run` does not say which
declaration is meant, and the file is the hint. A request that names only the file of a
symbol Knowledge does not match either; that Knowledge reaches the agent when it reads the file.
Matching is local and deterministic, with no model call.
A request that shares no signal injects nothing. Stored Knowledge needs no migration: its
signal comes from its current contract. A Knowledge about several files or symbols has one
signal per source and is relevant when any one of them matches.

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
that memory, so the Knowledge can be injected again. A resumed session keeps it, on every host:
the Knowledge arrives as prompt or tool context, which stays in the resumed history (unlike the
start context, which Copilot rebuilds), so it is not injected twice.
The shared budget (the native facts' share of `microskills_max_facts` and
`microskills_max_tokens`) applies to each injection, a prompt's or a read's, not cumulatively
over the session: Knowledge already given does not use it up.
When more Knowledge matches than the shared budget holds, the strongest match is kept first.
Strength of match is: a symbol named as a whole identifier together with its file (3), then a
file named by its full
path (2), then a file named by its bare file name (1); a Knowledge with several sources counts its strongest
matching signal. Equal matches are ordered by firing rate, highest first, and what still ties
keeps registration order, so the choice is deterministic and makes no model call.

### The read trigger

The second trigger is the agent reading a file a Knowledge covers (any of the
files it is about), even when the request never named it. It
runs on `PostToolUse` after a file-reading tool (`Read`, `read`, `view`) succeeds, with
`knowledge=on`, also when the loop guard is off, and only on a host verified to put that
context after the tool's result at the end of the conversation (`tool_context`: Claude Code,
Copilot, Pi). A host not verified gets nothing from this trigger. The same once-per-session
memory (`knowledge_given`) and the same budget, proof, lifecycle and forgotten gates apply, so a
Knowledge given by the prompt is not given again by the read, nor the reverse. The file must lie
inside the workspace. Every match is an exact path, so covering Knowledge is ordered by firing rate, then
registration order. A subagent's read, a failed
read, a shadow run and a replayed (queued) hook inject nothing.

**It cannot save the read.** Probed on 2026-11-24, no host accepts context for the model before
the tool runs, so the Knowledge is always injected after the read (`when: "after_read"`); there
is no pre-read path. The session state remembers the files read (`files_read`, emptied with
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
`trigger` (`"prompt"` or `"read"`), plus the usual `at`, `session_id` and `shadow`. A read
adds `when` (`"after_read"`). Both triggers add `read_before`: on a read, the file had been read
earlier in the session; on a prompt, one of the Knowledge's own files had been. Nothing is logged when nothing is injected, and
forgotten, stale-proof or budget-dropped Knowledge never appears. The triggers share this one kind.

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


A fact about several files or symbols is proposed as `sources`, at least two `{source,
symbol?}` entries, in place of `source` and `symbol`. Each source is proven as a single one is
(from the same session's observation, a partial read only for a declaration it crossed), and the
contract is the list of those proofs: the Knowledge is valid only while every one of them is.
Inspection lists all its sources. Knowledge that synthesizes other Knowledge is not supported;
a stored one of that kind has no proof, so it is never injected.

## Recorded-session evaluation

`tests/test_knowledge_pi.py::test_pi_hook_learns_from_recorded_active_sessions`
replays the sanitized Pi complete-read recording five times through the live hooks,
with distinct session IDs, an added simulated successful `pytest` command, and a
stub proposer returning one grounded file candidate. No lifecycle threshold or
proposal cadence is overridden. The following counts are `(stored, eligible for
rendering)` after each fold: `(0, 0), (1, 0), (1, 0), (1, 1), (1, 1)`.
The test also checks the hook output, forget/unforget, deletion and restoration.
The separate Copilot recording test exercises a second host. Workflow tests cover
file and symbol contracts, several sources, revision, warm-cache revalidation,
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
