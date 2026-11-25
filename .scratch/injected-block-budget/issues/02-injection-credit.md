# 02: Credit the facts the session was given

**What to build:** the block reports the ids of the facts it carries, across both layers, so the fold knows what the session was actually given. A fact the session was given, and whose waste did not occur, counts as having fired: the block did the work, and a useful fact must not lose its rate for succeeding. Spec: `.scratch/injected-block-budget/spec.md`.

**Blocked by:** None

**Status:** resolved

- [x] `injected_ids()` on the paid manual, and the composition reports both layers' ids
- [x] The fold seeds each layer with what the block carried, filtering to its own facts
- [x] A fact the session was given, exercised, and whose waste did not occur is credited as fired
- [x] A fact the session was not given keeps the plain detector reading
- [x] A fact that was not exercised gets no credit
- [x] `injected_ids` reaches `injection.json` as `rendered_ids`

## Comments

- 2026-11-25: before the fix `PrefixStage.injected_ids()` asked the environment layer only, and
  that layer held no facts, so `rendered_ids` was always `[]`, `seed_injected` always received an
  empty list, and the paid layer had no `injected_ids` at all. The firing counters still moved
  (4/4 then 5/5) because plain exercise detection is independent of the credit, which hid the
  gap: what was lost is the credit for a fact that prevents its waste.
- 2026-11-25: `tests/test_block_budget.py` covers the credit and the seeding; full suite 1 532
  passed, 40 skipped.
