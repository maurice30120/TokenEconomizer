# TokenEconomizer Knowledge

This context describes reusable knowledge derived from sessions in a workspace.

## Language

**Knowledge**:
A durable understanding of how the code works, grounded in one observed file or symbol, or in several observed sources that explain one coherent mechanism. The engine proves each source a proposal references, so a Knowledge is admitted and available in the cycle that proposes it; one sufficient observation is enough, with no second session and no confirmation count.
Knowledge is distinct from a native Fact and from a collection of separate file summaries.
Several Knowledge entries can cover the same file when they describe different mechanisms.
_Avoid_: Knowledge card, carte Knowledge

**Multi-source Knowledge**:
Knowledge supported by more than one observed source file or symbol, all explaining one mechanism. Each source has its own evidence, and the Knowledge is valid only while every one of them is.

**Knowledge Evidence**:
An observation supporting Knowledge whose validity establishes that the relevant code still matches the observed version, but does not establish that the finding is correct.

**Knowledge Contract**:
The evidence that determines whether a **Knowledge** entry remains valid in the current checkout.
Only entries with a valid **Knowledge Contract** qualify for semantic search.

**Work Sequence**:
A user message and the work that follows it until the next user message or the end of the session. A message with no work still starts a sequence.

**Knowledge Digest**:
The view the proposer reads: the newest **Work Sequences** of the folded sessions, ordered by message emission time, each with the refs of the **Knowledge Observations** it retained, plus the **Knowledge Catalogue** of that code, the **Knowledge Comments** about its refs and the **Read Co-occurrence** pairs. A sequence retains observations in read order while they fit its own 16 000 characters, so what one sequence drops can prove nothing. Its bounded message travels with it as context, outside that cap: only observations are charged.
_Avoid_: window, session digest

**Knowledge Catalogue**:
The retained code a **Knowledge Digest** shows the proposer, one entry per path and compatible version of the file, with every ref that hit it and the work sequence, session and read each ref names. Ranges of one version merge when they overlap, a complete read subsumes the partial reads of that version, and fragments that do not touch stay separate fragments of the entry. Another version of the file is another entry, even when a declaration's own fingerprint is unchanged.

**Read Co-occurrence**:
A pair of catalogue paths read in the same **Work Sequence**, with how many sequences show that pair. A signal that two files were explored together, never **Knowledge Evidence**: it cannot admit anything, and recurrence is not proof.

**Knowledge Comment**:
What the agent itself wrote: the visible text of one of its assistant messages, kept with the refs of the **Knowledge Observations** the call series it followed returned. A reply's text joins the series whose results are already there, and then that reply's own tool calls close the series, so a comment written beside the next call still belongs to the reads before it; a user message ends the window, and a series that returned no read owns nothing. An identical comment repeated is one entry with its occurrences and its provenance (session, sequence, position), and its text counts in the sequence's own 16 000 characters. A comment is untrusted data, never evidence: a finding it states, a hypothesis it guesses or a future requirement it expects never establishes a Knowledge, because only a retained code observation does.
_Avoid_: agent note, conclusion, rationale

**Digest Ref**:
The short stable name of one read a **Knowledge Digest** retains, and the only thing a **Knowledge** proposal cites: a ref resolves against the retained digest alone, never against a file path or a session. Several refs name the same code when they read one version, so a proposal names the read it means.
_Avoid_: source id, anchor

**Knowledge Observation**:
What a session actually read of a source: the whole file for a complete read, the returned lines for a partial one. Its scope is recorded; the part that was not read is never presented as observed.

**Read Capture**:
The bytes of a file kept by the hook as a Pi `read` returned them, so a partial read can be proved against the version it observed. Bounded per session, discarded once the session is folded, and never shown to the model as reading.

**Knowledge Signal**:
The symbol a Knowledge is about or, failing that, the file it is about, taken from its contract. A user request shares a signal when it names that symbol (as a whole identifier) or that file (by path or by file name). A tool call names it the same way: the signal found in the call's text, never a parsed command. A Knowledge with several sources has one signal per source.

**Relevant Knowledge**:
Knowledge that shares a Knowledge Signal with the user's current request, or that covers a file a tool call named (the signal found in the call's text, whatever the tool). Only Relevant Knowledge is ever given to the agent. It is given at session start, up to the startup share of the Knowledge allowance, and again when a request shares a signal or a tool call names a covered file; when none is relevant, none is given.
_Avoid_: matching knowledge, applicable knowledge

**Knowledge Allowance**:
What the conversation may receive of Knowledge in total: how many Knowledge entries and how many tokens, together with the share of both available at session start.
_Avoid_: knowledge budget, knowledge quota

**Startup Share**:
In `knowledge_injection=both` mode, the fraction of the Knowledge Allowance a session may be given at session start. What the startup does not use stays available for Knowledge given after a tool call. The `startup` mode uses the full allowance at session start; `tools` reserves it for tool calls.

**Knowledge Revision**:
A marker identifying a particular revision of a Knowledge entry, separate from its stable identity.
