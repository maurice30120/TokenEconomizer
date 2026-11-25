# 01: Propose up to eight mixed candidates

**What to build:** Let the existing shared proposer return up to eight native Facts and Knowledge candidates in one call, in any mix. The extra slots give Knowledge more room to appear and let the experiment measure the actual mix.

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] On an existing shared proposal tick, the model is asked for up to eight candidates across both types. TE considers at most the first eight in response order, without a quota per type.
- [x] Each candidate goes through the current admission rules for its type. Knowledge continues to require the existing file or symbol contract. A rejected candidate does not trigger another model call.
- [x] The current proposal cadence and the behavior when a shared call is unavailable are preserved.
- [x] Proposal and admission counts by type are observable for the experiment. Verify the mixed batch, cap and admission behavior through the existing session fold workflow with a simulated proposer.

## Answer

Verified through the fold workflow with a simulated shared batch. TE admitted six valid Knowledge candidates and one native Fact, rejected a malformed source path without losing later candidates, and discarded the ninth candidate. The per-type proposal and admission counts were also checked with actual Pi and Copilot model calls on controlled traces.
