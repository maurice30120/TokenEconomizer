# File-backed Knowledge

Knowledge is experimental and off by default. Set `knowledge=on` with `te config set`
or `TE_KNOWLEDGE=on` to enable it independently of the native mechanisms. It currently
accepts Claude Code `Read` results only when their transcript retains both complete-file
metadata and matching model-visible content. Partial, truncated, failed, transformed or
unverifiable reads are ignored. Other hosts and read formats do not yet supply evidence.

The proposer sees bounded excerpts of complete observed reads and identifies a source and
session. It runs on the existing micro-skills proposal cadence and uses TE's grounding,
confirmation, contradiction and firing thresholds. The proposal is a separate model call;
verification is local and makes no model call. Knowledge shares the configured micro-skills
injection limits with native facts. State is isolated by workspace path. `te microskills`
lists Knowledge and its proof status; its `forget` and `unforget` operations also apply.

Before each new injection TE hashes the current file and drops only Knowledge whose proof
no longer matches. Deletion and read errors fail closed; restoring the exact bytes restores
eligibility subject to the lifecycle. A revised Knowledge retains its identity but must earn
new confirmations. Resumed conversations may already contain prior context, which cannot be
removed retroactively. Knowledge is untrusted data: a matching hash does not establish that
the explanation is correct.
