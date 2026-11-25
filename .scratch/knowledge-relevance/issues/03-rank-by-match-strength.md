# 03: Rank Relevant Knowledge by strength of match

**What to build:** when more Relevant Knowledge matches than the shared budget holds, the Knowledge with the stronger match is kept first, then the one with the higher firing rate, instead of the order of registration. Update the Knowledge documentation.

**Blocked by:** 01

**Status:** resolved

- [x] With a budget too small for every match, the stronger match is the one injected
- [x] Equal matches are ordered by firing rate
- [x] The shared budget with native facts is still respected
- [x] Tested through the live hooks

## Comments

- 2026-11-25: `90ea1a5` narrowed `match_strength` to require the file alongside a named symbol, though the spec makes a request match on the symbol *or* the file, and deleted the prompt-side ranking tests. Both restored in `ad2c448` (`test_a_small_budget_keeps_the_stronger_match_then_the_higher_firing_rate`, `test_a_symbol_named_in_the_prompt_outranks_a_file_match`).
