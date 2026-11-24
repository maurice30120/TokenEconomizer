# TokenEconomizer Knowledge

This context describes reusable knowledge derived from sessions in a workspace.

## Language

**Knowledge**:
A reusable finding derived from a session and supported by evidence. Knowledge is distinct from a native Fact.

**Composed Knowledge**:
Knowledge that synthesizes at least two distinct existing Knowledge entries. Its validity depends on the validity of those entries at their referenced revisions.

**Knowledge Evidence**:
An observation supporting Knowledge whose validity establishes that the relevant code still matches the observed version, but does not establish that the finding is correct.

**Knowledge Observation**:
What a session actually read of a source: the whole file for a complete read, the returned lines for a partial one. Its scope is recorded; the part that was not read is never presented as observed.

**Read Capture**:
The bytes of a file kept by the hook as a Pi `read` returned them, so a partial read can be proved against the version it observed. Bounded per session, discarded once the session is folded, and never shown to the model as reading.

**Knowledge Revision**:
A marker identifying a particular revision of a Knowledge entry, separate from its stable identity.
