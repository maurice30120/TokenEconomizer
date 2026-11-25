# 01: One budget over the injected block

**What to build:** `microskills_max_facts` and `microskills_max_tokens` cap the block the session receives, not one layer of it. The environment layer renders first within the allowance, the paid manual fills the remainder one line at a time, a line that does not fit is left out whole and the next candidate is still tried, and the block carries one header. Either layer may be absent and runs through the same budgeted path. Spec: `.scratch/injected-block-budget/spec.md`.

**Blocked by:** None

**Status:** resolved

- [x] The composed block never exceeds either cap, header included
- [x] A layer alone is capped too, and the environment layer keeps its own ids when it renders alone
- [x] A line that does not fit is skipped whole, never cut, and the next candidate is tried
- [x] Nothing fits → empty block, no ids
- [x] The configured caps reach the environment layer
- [x] The settings reference says the caps cover the block and every layer
- [x] Tested through the live hooks (`te microskills` re-renders the block the next session gets)

## Comments

- 2026-11-25: measured before the fix on the CodeTour campaign: 5 facts and 1 336 characters
  (≈330 tokens) injected for a 4 fact / 150 token budget. `InjectionConfig` documented "caps on
  the environment-fact block" while `plugin/config.py` documented "caps on the injected block";
  only `EnvFactsDistiller` read them, and its state for that repository was empty, so the whole
  block came from the paid layer, uncapped.
- 2026-11-25: `tests/test_block_budget.py` covers the cases above; full suite 1 532 passed, 40
  skipped. On the campaign repository the same state now renders 2 facts and 467 characters.
