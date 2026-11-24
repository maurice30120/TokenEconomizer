# 03: Rank Relevant Knowledge by strength of match

**What to build:** when more Relevant Knowledge matches than the shared budget holds, the Knowledge with the stronger match is kept first, then the one with the higher firing rate, instead of the order of registration. Update the Knowledge documentation.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] With a budget too small for every match, the stronger match is the one injected
- [ ] Equal matches are ordered by firing rate
- [ ] The shared budget with native facts is still respected
- [ ] Tested through the live hooks
