# TokenEconomizer Knowledge

This context describes reusable knowledge derived from sessions in a workspace.

## Language

**Knowledge**:
A reusable finding derived from a session and supported by evidence. Knowledge is distinct from a native Fact.

**Multi-source Knowledge**:
Knowledge about several files or symbols, each with its own proof. It is valid only while every proof is, and it is relevant when the signal of any one source matches.

**Knowledge Evidence**:
An observation supporting Knowledge whose validity establishes that the relevant code still matches the observed version, but does not establish that the finding is correct.

**Knowledge Observation**:
What a session actually read of a source: the whole file for a complete read, the returned lines for a partial one. Its scope is recorded; the part that was not read is never presented as observed.

**Read Capture**:
The bytes of a file kept by the hook as a Pi `read` returned them, so a partial read can be proved against the version it observed. Bounded per session, discarded once the session is folded, and never shown to the model as reading.

**Knowledge Signal**:
The symbol a Knowledge is about, together with the file it lives in, or, failing that, the file it is about. A user request shares a symbol signal only when it names both, since a symbol name alone does not say which declaration is meant; it shares a file signal by naming the file. A Knowledge with no signal in common with a request is not relevant to it.

**Relevant Knowledge**:
Knowledge that shares at least one Knowledge Signal with the user's current request. Only Relevant Knowledge is ever given to the agent; when none is relevant, none is given.

**Knowledge Revision**:
A marker identifying a particular revision of a Knowledge entry, separate from its stable identity.
