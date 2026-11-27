# TokenEconomizer Knowledge

This context describes reusable knowledge derived from sessions in a workspace.

## Language

**Knowledge**:
A durable understanding of how the code works, grounded in one observed file or symbol, or in several observed sources that explain one coherent mechanism. Knowledge is distinct from a native Fact and from a collection of separate file summaries.
Several Knowledge entries can cover the same file when they describe different mechanisms.

**Multi-source Knowledge**:
Knowledge supported by evidence for each of its source files or symbols.

**Knowledge Evidence**:
An observation supporting Knowledge whose validity establishes that the relevant code still matches the observed version, but does not establish that the finding is correct.

**Knowledge Contract**:
The evidence that determines whether a **Knowledge** entry remains valid in the current checkout.
Only entries with a valid **Knowledge Contract** qualify for semantic search.

**Work Sequence**:
A user message and the work that follows it until the next user message or the end of the session. A message with no work still starts a sequence.

**Knowledge Observation**:
What a session actually read of a source: the whole file for a complete read, the returned lines for a partial one. Its scope is recorded; the part that was not read is never presented as observed.

**Read Capture**:
The bytes of a file kept by the hook as a Pi `read` returned them, so a partial read can be proved against the version it observed. Bounded per session, discarded once the session is folded, and never shown to the model as reading.

**Knowledge Signal**:
The symbol a Knowledge is about or, failing that, the file it is about, taken from its contract. A user request shares a signal when it names that symbol (as a whole identifier) or that file (by path or by file name). A Knowledge with several sources has one signal per source.

**Relevant Knowledge**:
Knowledge that shares a Knowledge Signal with the user's current request, or that covers a file the agent has read. Only Relevant Knowledge is ever given to the agent. It is given at session start, up to the startup share of the Knowledge allowance, and again when a successful read covers it; when none is relevant, none is given.
_Avoid_: matching knowledge, applicable knowledge

**Knowledge Allowance**:
What the conversation may receive of Knowledge in total: how many Knowledge entries and how many tokens, together with the share of both available at session start.
_Avoid_: knowledge budget, knowledge quota

**Startup Share**:
The fraction of the Knowledge Allowance a session may be given at session start. What the startup does not use stays available for Knowledge given after a read.

**Knowledge Revision**:
A marker identifying a particular revision of a Knowledge entry, separate from its stable identity.
