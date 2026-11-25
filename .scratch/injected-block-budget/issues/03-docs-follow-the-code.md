# 03: Documentation follows the code

**What to build:** where the documentation disagreed with the shipped behaviour, the documentation changes. The Knowledge glossary stops claiming that Relevant Knowledge is never given at session start (commit `fe8041a` delivers it, within `knowledge_startup_share`), the settings reference describes the one budget over the block, and the micro-skills vocabulary gets its own glossary behind a glossary map. Spec: `.scratch/injected-block-budget/spec.md`.

**Blocked by:** None

**Status:** resolved

- [x] `GLOSSARY.md` states that Relevant Knowledge is given at session start up to the startup share, and after a read
- [x] `Knowledge Allowance` and `Startup Share` defined
- [x] `GLOSSARY-MAP.md` names the two contexts and how they relate
- [x] `tokeneconomizer/microskills/GLOSSARY.md` defines Fact, Native Fact, Environment Fact, Injected Block, Block Budget, Injection Credit, Firing Gate, Micro-skills
- [x] The settings reference and `docs/PLUGIN.md` describe the block budget as covering every layer
- [x] `te microskills` marks a fact `INJECTED` only when the block the next session receives carries it, and `gate ok` when only the gate is cleared

## Comments

- 2026-11-25: `GLOSSARY.md` said of Relevant Knowledge "never at session start" while `fe8041a`
  ("Deliver Knowledge at session start"), `knowledge_startup_share=0.5` and
  `controller.py`'s startup trigger do exactly that; issue
  `.scratch/knowledge-relevance/issues/01-prompt-triggered-injection.md` still carries the old
  criterion. Decision taken during the campaign: the code and the startup experiment are
  authoritative, the documentation follows.
- 2026-11-25: `te microskills` printed `INJECTED` from the firing gate alone, so three facts read
  as injected while the block carried two; the campaign counted them as delivered. The command now
  re-renders the block the next session would get and marks what it carries.
