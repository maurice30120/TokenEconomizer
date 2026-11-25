# One budget over the injected block, not one per layer

The block a session receives is composed by two layers — the free environment facts and the paid
manual — and the caps a person configures (`microskills_max_facts`, `microskills_max_tokens`)
apply to that block as a whole: the free layer renders first within the allowance, the paid manual
fills what is left line by line, and a line that does not fit is left out whole. The block is what
the agent actually reads and what the person believes they capped, so a per-layer cap would count
the same allowance twice and leave the total unbounded.

## Considered Options

- **Per-layer caps** — each layer budgets itself, the total is the sum. Rejected: two numbers in
  the settings would produce a third, undeclared total, and the free layer's own caps (4 facts,
  150 tokens) already consumed the whole allowance alone.
- **Document the observed behaviour** — the paid layer keeps rendering everything, the settings
  page says the caps only bind the free layer. Rejected: the documentation said "caps on the
  injected block" in one place and "caps on the environment-fact block" in another, and a
  campaign announced a 150-token budget while sessions received ≈330.

## Consequences

- A 150-token allowance now starves the paid layer: on the CodeTour repository the block fell from
  five facts to two. Raising the budget is a deliberate act, not an accident of composition.
- The line that does not fit is dropped, so a long fact can push out shorter ones behind it; the
  order of `Distiller.facts` therefore decides who competes for the remainder.
- Both layers report the ids they contributed, which is what lets the fold credit a fact the
  session was given (see `.scratch/injected-block-budget/issues/02-injection-credit.md`).
