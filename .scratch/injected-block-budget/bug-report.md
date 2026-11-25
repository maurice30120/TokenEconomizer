# Bug report: `microskills_max_facts` / `microskills_max_tokens` bind only the environment layer

Filed as https://github.com/maurice30120/TokenEconomizer/issues/1 (2026-11-25, label `bug`).
Fixed locally on `knowledge-relevance-integration`, not committed. Implementation tickets:
`01-one-block-budget.md`, `02-injection-credit.md`, `03-docs-follow-the-code.md`.

The text below is the issue body, kept here so the repository and the tracker say the same thing.
The defect is inherited, not ours — `microsoft/TokenEconomizer` `origin/main` at `e7cc759`
(2026-11-25), the merge base of our branch, carries it, and it dates back at least to `40b92d6`
(2026-10-17, "Migrate the plugin from main"), 386 commits before that main. If the defect is ever
contributed upstream, this text can be sent as-is.

---

## Summary

`microskills_max_facts` and `microskills_max_tokens` are documented as "caps on the injected
block", but they reach `EnvFactsDistiller` only. The paid layer (`microskills.Distiller`) renders
every firing-gated fact it has, with no cap at all, and `ComposedDistiller` never re-budgets the
result. With `microskills=on` — which is `envfacts+distiller` — a session therefore receives an
unbounded block as soon as the paid layer holds facts, and with `microskills=distiller` the caps
are ignored outright.

## Impact

- A person who sets a budget does not get it. Measured on a real repository (CodeTour, Pi 1.6.0,
  `microskills=on`, configured 4 facts / 150 tokens): the block carried 5 facts and 1 336
  characters, ≈330 tokens — more than twice the announced allowance.
- The default configuration is the worst case. `docs/PLUGIN.md` notes that the free layer forms
  almost nothing once an environment is set up properly, so on most repositories the block comes
  from the paid layer alone, which is the layer that ignores the caps.
- Capping the block is what makes the cost of micro-skills predictable; without it the setting is
  decorative.

## How it was found

A comparison campaign on CodeTour configured budgets, then compared what the session actually
received against them. Three observations, in order:

1. The injected text in the session record was 1 336 characters for a 150-token budget. The
   block and the ledger agreed on the length, so the injection itself was fine — only its size
   was wrong.
2. `injection.json` had `rendered_ids: []` although the block carried five facts, and the
   session record's `injected_ids` was empty. `PrefixStage.injected_ids()` returned `[]`.
3. Reading the render path explained both: `PrefixStage.__init__` passes `caps` to
   `EnvFactsDistiller` only, `Distiller.render` has no cap, `ComposedDistiller.render` concatenates
   the two blocks, and `injected_ids()` asks the environment layer alone. On that repository the
   environment layer's state held no facts at all, so the whole block came from the paid layer —
   which is also why the ids were always empty.

Nothing in the tooling compared the announced budget with the delivered block; the cap had simply
never been observed against its documentation.

## Root cause

- `tokeneconomizer/microskills/stage.py`, `PrefixStage.__init__`: `caps` is built and handed to
  `EnvFactsDistiller`, never to `Distiller` nor to `ComposedDistiller`; the `distiller` profile
  assigns the bare `Distiller` as the stage's distiller, so nothing caps it either.
- `tokeneconomizer/microskills/distiller.py`, `Distiller.render`: renders every
  `f.injectable()` fact, no cap, and no `injected_ids()`.
- `tokeneconomizer/microskills/stage.py`, `ComposedDistiller.render` / `injected_ids`: concatenates
  both blocks and reports the environment layer's ids only.
- The two settings references disagree, which is how the defect survived review:
  `plugin/config.py` says "caps on the injected block", `config.py` says
  "Caps on the environment-fact block (`envfacts`)".
- Consequence for traceability: `plugin/fold.py` writes `rendered_ids: stage.injected_ids()`, so
  `rendered_ids` is `[]` whenever the block comes from the paid layer, and
  `seed_injected(sess["injected_ids"])` always seeds an empty list. A fact the session was given,
  whose waste therefore did not occur, is counted as *not* having fired and loses rate for
  succeeding.

## Reproduction

With the code as of `e7cc759`, and no environment facts (the common case), five firing-gated paid
facts produce five lines whatever the caps say:

```python
import tempfile
from tokeneconomizer.config import InjectionConfig
from tokeneconomizer.microskills import PrefixStage
from tokeneconomizer.microskills.distiller import Fact

stage = PrefixStage(InjectionConfig(enabled=True, profile="distiller",
                                    max_facts=2, max_tokens=300),
                    "acme/widget", tempfile.mkdtemp(), fresh=True)
# `distiller` alone: before the fix this is the bare Distiller, after it a ComposedDistiller.
dist = getattr(stage.distiller, "dist", stage.distiller)
for i in range(5):
    fact = Fact({"id": f"f{i}", "claim": f"fact {i}",
                 "injection": f"learned line number {i}, about forty chars",
                 "detector": {"scope": "ran_tests", "fired": "command_failed"}})
    fact.life.state = "ACTIVE"
    fact.life.fire_num = fact.life.fire_den = 4       # clears the firing gate
    dist.facts[fact.id] = fact
block = stage.render()
print(len(block), [l for l in block.splitlines() if l.startswith("- ")])
```

Before the fix: `5` lines. After the fix: `2` lines and 159 characters, and
`stage.injected_ids()` returns `['f0', 'f1']`.

## Fix we run locally

On our branch, uncommitted, with `tests/test_block_budget.py` covering each point:

1. **One budget over the block.** `ComposedDistiller(env, dist, max_facts, max_tokens)` renders
   the environment layer first, then fills the remaining allowance from the paid layer one line at
   a time; a line that does not fit is dropped whole and the next candidate is still tried; one
   header; either layer may be absent and goes through the same budgeted path. `0` falls back to
   `envfacts.MAX_FACTS` / `MAX_TOKENS`, the same fallback the environment layer uses.
2. **Ids and credit.** `Distiller` gained `injectable_items()`, `header`, `injected_ids()` and
   `seed_injected()`; the composition reports the union of both layers' ids, so `rendered_ids` is
   populated and `seed_injected` receives what the session was given. `Fact.observe(...,
   injected=True)` counts a fact the session was given, exercised, whose waste did not occur, as
   having fired — the rule `envfacts` already applies to its `form_repair` family.
3. **Docs and reporting.** `config.py` and `docs/PLUGIN.md` now say the caps bind the block and
   every layer; `te microskills` re-renders the block the next session would receive and marks
   `INJECTED` only for the facts it carries, `gate ok` for one the budget left out. The old marker
   read the firing gate alone, which is what made the 5-fact block look intended.

Tests: full suite `1533 passed, 40 skipped`.

## Open questions

For a future upstream discussion, not decisions we need to take now:

- **Where the budget belongs.** We chose one budget over the block. The alternative is a cap per
  layer with a declared total; we rejected it because two settings would produce a third,
  undeclared number.
- **The order lines compete in.** Today the environment layer wins and the paid layer fills the
  remainder in `Distiller.facts` insertion order, so a long fact can push out shorter ones behind
  it. A priority (firing rate, family) may deserve to be explicit.
- **Whether the ids should survive a fold that never ran.** `injected_ids` is per session; a
  session folded after a crash has no ids, and today that silently means "given nothing".
