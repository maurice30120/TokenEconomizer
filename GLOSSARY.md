# TokenEconomizer Knowledge

This context describes reusable knowledge derived from sessions in a workspace.

## Language

**Knowledge**:
A durable understanding of how the code works, grounded in code a session actually observed: one file, one symbol, or several sources explaining one mechanism. Knowledge is distinct from a native Fact and from a collection of separate file summaries.
Several Knowledge entries can cover the same file when they describe different mechanisms.

**Multi-source Knowledge**:
Knowledge supported by evidence for each of its source files or symbols.

**Knowledge Evidence**:
An observation supporting Knowledge whose validity establishes that the relevant code still matches the observed version, but does not establish that the finding is correct.

**Knowledge Contract**:
The evidence that determines whether a **Knowledge** entry remains valid in the current checkout.
Only entries with a valid **Knowledge Contract** qualify for search and injection.

**Knowledge Observation**:
What a session actually read of a source: the whole file for a complete read, the returned lines for a partial one. Its scope is recorded; the part that was not read is never presented as observed.

**Read Capture**:
The bytes of a file kept by the hook as a Pi `read` returned them, so a partial read can be proved against the version it observed. Bounded per session, discarded once the session is folded, and never shown to the model as reading.

**Knowledge Signal**:
The symbol a Knowledge is about or, failing that, the file it is about, taken from its contract. A user request shares a signal when it names that symbol (as a whole identifier) or that file (by path or by file name). A Knowledge with several sources has one signal per source.

**Knowledge Nearness**:
How close a user request and a Knowledge's text are in the local index: the cosine similarity of the vectors the shipped lexical vectorizer makes from their words and word fragments. A request that names no Knowledge Signal can still be near a card and receive it. Nearness is lexical -- shared words, not shared meaning -- so a request in one language is not near a card in another, and a card reached that way never displaces or replaces one the exact signals named.

**Relevant Knowledge**:
Knowledge that shares a Knowledge Signal with the user's current request, or that covers a file the agent has read, or that the request is near. Only Relevant Knowledge is ever given to the agent: after a successful read that covers it, at a prompt that names it or that is near it, and, on a resume, the block an earlier start of that conversation recorded; when none is relevant, none is given.
_Avoid_: matching knowledge, applicable knowledge

**Knowledge Allowance**:
What the conversation may receive of Knowledge in total: how many Knowledge entries and how many tokens. Both bound the whole conversation, over every turn and trigger; no part of the allowance is reserved for a session start.
_Avoid_: knowledge budget, knowledge quota

**Knowledge Revision**:
Retired: a Knowledge keeps one stable identity and one claim; a claim that changed is a new Knowledge.
