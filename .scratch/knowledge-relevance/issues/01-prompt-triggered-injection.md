# 01: Inject Relevant Knowledge from the user prompt

**What to build:** a user request that names the symbol or the file of a Knowledge (its Knowledge Signal, taken from the Knowledge's contract) brings that Knowledge into the session as Relevant Knowledge. A request that shares no signal injects nothing. Knowledge is no longer injected at session start. On a host whose hook output does not reach the model, no Knowledge is injected. Existing stored Knowledge works without relearning. Proof validation, lifecycle and firing gates, forgetting and the shared fact and token budget with native facts stay as they are. Native facts keep their session-start injection. Update the Knowledge documentation for this behaviour. Spec: `.scratch/knowledge-relevance/spec.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] A prompt naming a Knowledge's symbol or file injects it; a prompt sharing no signal injects nothing
- [ ] A Knowledge whose contract has no symbol is matched on its file
- [ ] Nothing from Knowledge is injected at session start
- [ ] A host without prompt context injects no Knowledge
- [ ] Invalid proof, forgotten, or ineligible Knowledge is never injected
- [ ] Native facts and the shared budget behave as before
- [ ] A selection error leaves the hook output empty and the session unaffected
- [ ] After an injection, the next request keeps exactly the same cached prefix (tools, system prompt, earlier conversation) on each supported host; on Pi, where context goes into the system prompt section, an injection that varies by prompt must not rewrite that section, or it is delivered another way
- [ ] Tested through the live hooks
