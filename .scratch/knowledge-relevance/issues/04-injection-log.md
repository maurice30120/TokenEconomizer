# 04: Log which Knowledge was injected and why

**What to build:** each Knowledge injection is recorded with the identity of the Knowledge and the Knowledge Signal that triggered it, so a campaign can prove what the agent was given and why without relying on the transcript. The injection field of the log is no longer empty for Knowledge. Update the Knowledge documentation.

**Blocked by:** 01

**Status:** ready-for-agent

- [x] Every injection records the Knowledge identity and the triggering signal
- [x] Nothing is recorded when nothing is injected
- [x] Forgotten or ineligible Knowledge never appears as injected
- [x] Tested through the live hooks
