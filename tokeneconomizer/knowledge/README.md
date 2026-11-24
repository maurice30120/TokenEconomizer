# File-backed Knowledge

Knowledge is experimental and off by default. Set `knowledge=on` with `te config set`
or `TE_KNOWLEDGE=on` to enable it independently of the native mechanisms. It currently
accepts:

- Claude Code `Read` results with complete-file metadata and matching model-visible content;
- Pi `read` results on the active session branch, without offsets, limits, truncation details
  or truncation notices. This adapter was checked against the locally installed Pi 1.2.0;
- Copilot `view` file results from session format version 1.0.105, without a range or avoided
  large output, with telemetry confirming that the whole result reached the model. Files at or
  above 20 KiB and sessions without the required telemetry are rejected conservatively.

Partial, truncated, failed, transformed or unverifiable reads are ignored. Other hosts,
Copilot versions and read formats do not yet supply evidence. The Pi and Copilot test fixtures
are sanitized local sessions recorded with a simulated model provider; their file paths and Pi
system prompt were replaced, while the tool calls and results were retained.

The proposer sees bounded excerpts of complete observed reads and identifies a source and
session. It runs on the existing micro-skills proposal cadence and uses TE's grounding,
confirmation, contradiction and firing thresholds. The proposal is a separate model call;
verification is local and makes no model call. Knowledge shares the configured micro-skills
injection limits with native facts. State is isolated by workspace path. `te microskills`
lists Knowledge identity, revision, lifecycle, proof status, and source session and path,
including forgotten records. Use `te microskills forget ID` to suppress one and
`te microskills unforget ID` to restore its saved lifecycle; injection still requires
a valid proof and the usual lifecycle gates.

Before each new injection TE hashes the current file and drops only Knowledge whose proof
no longer matches. Deletion and read errors fail closed; restoring the exact bytes restores
eligibility subject to the lifecycle. A revised Knowledge retains its identity but must earn
new confirmations. Resumed conversations may already contain prior context, which cannot be
removed retroactively. Knowledge is untrusted data: a matching hash does not establish that
the explanation is correct.

## Symbol contracts

The optional `symbol` proposal field names one unqualified declaration in a complete
observed source. Tree-sitter must parse the file without errors and resolve the name
uniquely. The contract hashes the declaration's non-comment tokens, including decorators;
changes elsewhere and comment-only changes do not invalidate it. Ambiguous names, missing
grammars and parse errors produce a file proof with a recorded fallback reason and requested
symbol. Existing symbol proofs fail closed if the grammar, parser, or recorded version is
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
Already-injected context in a resumed conversation cannot be retracted.

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
