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
