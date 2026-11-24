# 05: Inject Relevant Knowledge when the agent reads a covered file

**What to build:** when the agent reads a file that a Knowledge covers, that Knowledge is injected at that moment even if the request never named the file. It is not injected twice with the prompt trigger, and it is logged with its signal. The log also says when the file had already been read earlier in the session, so a campaign can tell when the Knowledge came too late to save the read. Each host is verified separately; a host that does not accept context after a tool call receives no injection from this trigger. Update the Knowledge documentation with the verified hosts.

**Blocked by:** 01, 02, 04

**Status:** ready-for-agent

- [ ] Probe first, on Copilot and Pi: does a hook before the tool call (`PreToolUse` / Pi `tool_call`) accept context for the model, is it seen before the read result, is the tool not denied, and does the cached prefix stay unchanged? Record the result per host in the documentation
- [ ] On a host where the probe succeeds, the Knowledge is injected **before** the read runs (the file is known from the tool input), so it can save the read; the log records the injection as made before the read
- [ ] On a host where the probe fails, fall back to the context after the tool call (`PostToolUse`), logged as made after the read; on a host that accepts neither, nothing is injected
- [ ] Reading a covered file injects its Knowledge on a host that accepts context after a tool call
- [ ] A Knowledge already injected by prompt is not injected again by the read
- [ ] The log records the identity, the signal and whether the file was read before the injection
- [ ] A host that does not accept context after a tool call injects nothing from this trigger
- [ ] After a read-triggered injection, the next request keeps exactly the same cached prefix on each host
- [ ] Verified hosts are recorded in the documentation
- [ ] Tested through the live hooks
