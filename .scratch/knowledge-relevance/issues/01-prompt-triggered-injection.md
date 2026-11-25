# 01: Inject Relevant Knowledge from the user prompt

**What to build:** a user request that names the symbol or the file of a Knowledge (its Knowledge Signal, taken from the Knowledge's contract) brings that Knowledge into the session as Relevant Knowledge. A request that shares no signal injects nothing. Knowledge is no longer injected at session start. On a host whose hook output does not reach the model, no Knowledge is injected. Existing stored Knowledge works without relearning. Proof validation, lifecycle and firing gates, forgetting and the shared fact and token budget with native facts stay as they are. Native facts keep their session-start injection. Update the Knowledge documentation for this behaviour. Spec: `.scratch/knowledge-relevance/spec.md`.

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] A prompt naming a Knowledge's symbol or file injects it; a prompt sharing no signal injects nothing
- [x] A Knowledge whose contract has no symbol is matched on its file
- [x] Nothing from Knowledge is injected at session start
- [x] A host without prompt context injects no Knowledge
- [x] Invalid proof, forgotten, or ineligible Knowledge is never injected
- [x] Native facts and the shared budget behave as before
- [x] A selection error leaves the hook output empty and the session unaffected
- [ ] After an injection, the next request keeps exactly the same cached prefix (tools, system prompt, earlier conversation) on each supported host; on Pi, where context goes into the system prompt section, an injection that varies by prompt must not rewrite that section, or it is delivered another way
  - Not ticked: Pi verified offline (message, section unchanged: Node test + Pi 1.5.2 source); opencode gets no Knowledge (its plugin only writes the system prompt); Claude Code, Copilot, Droid and Hermes deliver prompt context after the prompt, not confirmed against a live session here.
- [x] Tested through the live hooks

## Comments

- 2026-11-25: the prompt trigger was found deleted at HEAD by the integration review. Commit `90ea1a5` (multi-file Knowledge maps) removed `knowledge_on_prompt`, `_relevant_knowledge`, the `user_prompt` wiring, the `hookqueue` exemption and Pi's `promptMessage` delivery, then rewrote the docs, `GLOSSARY.md` and the tests to match — so this ticket's criteria were no longer true on the branch. Restored in `ad2c448`, adapted to multi-source Knowledge. The cached-prefix box stays unticked: no live host session was run for the prompt trigger.
