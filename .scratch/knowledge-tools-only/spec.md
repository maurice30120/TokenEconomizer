# Knowledge only where a mention names it

Status: ready-for-agent

## Problem Statement

A person using TokenEconomizer with Knowledge enabled can choose where Relevant Knowledge is
given: at session start, after a tool call, or both (the default). A local benchmark on Pi
(2026-11-27, three runs per variant, blind evaluation) judged the tool-call variant best and
cheapest; giving Knowledge at session start too cost the most and judged no better. The startup
path also carries its own share of the Knowledge Allowance, a restoration step when Copilot
rebuilds a resumed conversation, and a second pass through the state lock that a running fold can
hold — one session of the benchmark received no Knowledge at all for that reason.

So the default spends context and money on Knowledge before anyone knows it is needed, the
setting offers modes that lose, and the code keeps paths nobody should run. The decision is
recorded in ADR 0002 and the glossary already reflects it.

## Solution

Relevant Knowledge is given only right after a mention names it, never at session start:

- After a tool call that names a Knowledge Signal (a covered file by path or by file name, or a
  contract's symbol), exactly as the measured tool-call variant does today, with the whole
  Knowledge Allowance.
- After a user request that names a covered file, by path or by file name — only on agents that
  cannot receive Knowledge after a tool call (today Hermes Agent and Factory Droid). A symbol named
  alone in a request is no mention.

The `knowledge_injection` setting and the startup share go away; `knowledge=on|off` is the only
switch. Micro-skills are untouched: their facts are still injected at session start.

## User Stories

1. As a person using Pi with Knowledge on, I want no Knowledge in the session-start context, so that I do not pay for cards before the agent reaches the code they cover.
2. As a person using the Copilot CLI with Knowledge on, I want no Knowledge in the session-start context, so that startup context holds only what is always useful.
3. As a person resuming a Copilot conversation, I want no Knowledge re-added at the rebuilt start, so that resume behaves like a fresh start.
4. As a person resuming a Copilot conversation that was given startup Knowledge before this change, I want those cards to become eligible again after tool calls, so that Knowledge the model no longer sees is not counted as given.
5. As a person resuming such a conversation, I want the tokens those startup cards used to return to the allowance, so that the tool-call trigger is not starved by Knowledge that left the context.
6. As an agent on Pi, Copilot or Claude Code, I want Relevant Knowledge right after a tool call names a covered file, so that I read it next to the code it explains.
7. As an agent, I want a tool call that names a covered file by its bare file name to count, so that `cat stage.py` behaves like `cat path/to/stage.py`.
8. As an agent, I want a tool call that names a contract's symbol to count, so that a search for a function brings the Knowledge about it.
9. As an agent, I want a tool call that names several covered files to bring their Knowledge in mention order, so that the first file I asked for comes first.
10. As an agent, I want each Knowledge given at most once while it stays in context, so that repeated reads do not repeat it.
11. As a person, I want the tool-call trigger to have the whole Knowledge Allowance (cards and tokens), so that nothing is held back for a startup that no longer happens.
12. As a person who configured `knowledge_max_cards` or `knowledge_max_tokens`, I want those limits to keep their meaning, so that my caps still bound what a conversation receives.
13. As a person using Claude Code, I want no Knowledge after a prompt, only after tool calls, so that one session never runs two triggers.
14. As a person using Pi or Copilot, I want no Knowledge after a prompt, so that the measured behaviour is the shipped behaviour.
15. As a person using Hermes Agent or Factory Droid, I want Knowledge after a request that names a covered file, so that I keep a path to Knowledge on an agent that cannot receive it after a tool call.
16. As a person using Hermes Agent or Factory Droid, I want a request that names only a symbol to bring nothing, so that Knowledge follows a named file, never a guess.
17. As a person using Hermes Agent or Factory Droid, I want the prompt trigger active whenever Knowledge is on, so that I do not need a mode to get it.
18. As a person using an agent whose prompt context cannot vary without rewriting its cached prefix, I want still no prompt Knowledge, so that the prompt cache stays intact.
19. As a person with `knowledge=off`, I want no Knowledge anywhere, so that the switch stays the one control.
20. As a person in shadow mode, I want no Knowledge given while it still logs what it would do, so that shadow keeps its meaning.
21. As a person whose config file still sets `knowledge_injection`, I want it ignored without an error, so that my config keeps loading after the upgrade.
22. As a person whose config file still sets `knowledge_startup_share`, I want it ignored without an error, so that an old tuning does not break anything.
23. As a person whose environment still sets `TE_KNOWLEDGE_INJECTION` or `TE_KNOWLEDGE_STARTUP_SHARE`, I want it ignored, so that a forgotten shell variable changes nothing.
24. As a person running `te config set knowledge_injection=tools`, I want an answer saying the setting no longer exists and Knowledge is given only after a mention, so that I understand why nothing changed.
25. As a person running `te config unset knowledge_injection`, I want it to succeed and remove the stale key, so that I can clean up my config.
26. As a person reading `te config show`, I want no `knowledge_injection` or startup share listed, so that the settings shown are the settings that act.
27. As a person reading the config skill or the Knowledge README, I want them to describe one behaviour, so that the docs match the code.
28. As a person using micro-skills, I want the session-start facts block exactly as before, so that this change has no side effect on micro-skills.
29. As a person using micro-skills on Copilot, I want a resumed conversation to get its facts block back as before, so that only Knowledge's restoration goes away.
30. As a person using the repository map, tool pruning or the loop guard, I want them unchanged, so that only Knowledge delivery moves.
31. As a maintainer, I want the startup Knowledge code removed rather than disabled, so that no unused path keeps a second pass through the state lock.
32. As a maintainer, I want the host capability that only served startup Knowledge removed, so that host classes declare only what something reads.
33. As a maintainer, I want the events a session already logged (`knowledge` with `trigger=startup`) still readable, so that history and reports from older sessions keep working.
34. As a maintainer, I want session state written by older versions (`knowledge_startup`, `knowledge_given`, `knowledge_tokens`) still read without error, so that sessions running across the upgrade do not fail.
35. As a maintainer, I want the change checked against a recorded session, so that the decision is verified on real hook traffic, not only unit tests.

## Implementation Decisions

- **Session start (live controller).** The session-start handler no longer computes or emits a
  Knowledge block, for fresh and resumed sessions alike. The micro-skills, tool-pruning notices,
  repository map, history and fold steps of that handler are unchanged and keep their order.
- **Resume of an older session.** When a resumed session's state holds startup cards
  (`knowledge_startup`), the handler drops their ids from `knowledge_given`, subtracts their
  tokens from `knowledge_tokens` (never below zero), and removes `knowledge_startup`. It restores
  nothing. This is pure state bookkeeping and needs no lock on the Knowledge stage.
- **Knowledge selection.** The startup share disappears from the allowance arithmetic: every
  trigger computes what is left from the full `knowledge_max_cards` and `knowledge_max_tokens`.
  The stage's startup restoration operation is removed.
- **Tool-call trigger.** Unchanged in matching (path, bare file name, contract symbol, mention
  order across files, one card once per context). Its enabling condition becomes: Knowledge on,
  not shadow, host verified for after-tool context, tool call names a covered signal.
- **Prompt trigger.** Enabled when Knowledge is on, not shadow, and the host accepts prompt
  context, accepts prompt Knowledge, and does **not** accept after-tool context. Its matching is
  restricted to files: a request matches a Knowledge only by a source's file path or bare file
  name, never by a symbol. The stage gains a way to ask for relevance by file only (the
  tool-call path keeps symbol matching); the matching strengths for path and file name are
  unchanged.
- **Hosts.** The capability flag that only gated startup Knowledge is removed from the host
  model and from Pi and Copilot. No host gains or loses after-tool or prompt context.
- **Settings.** `knowledge_injection` and `knowledge_startup_share` are removed from the settings
  model, validation, environment mapping and `te config show`. They become retired keys: read
  from a config file or the environment, they are ignored without error and without a warning
  line; `te config set` refuses them with a message saying the setting no longer exists and that
  Knowledge is given only after a mention; `te config unset` accepts them and removes them.
- **CLI help and docs.** The CLI's settings help, the config skill and the Knowledge README
  describe the single behaviour. `GLOSSARY.md` and ADR 0002 are already updated on this branch.
- **Compatibility surface.** No on-disk name is renamed. Old `knowledge` events with
  `trigger=startup` and old session-state keys stay readable; new code simply never writes them.
- **Earlier specs.** The specs and issues under `knowledge-startup-experiment`,
  `knowledge-relevance` and `tool-call-reads` that describe startup delivery or symbol matching
  in prompts are superseded by this spec; append a short `## Comments` note to each saying so.

## Testing Decisions

- A good test drives the real hook with a host payload and asserts on what the hook answers (the
  context the model would receive), never on private helpers or state layout — except where state
  carried over from an older version is the input under test.
- **Main seam: the live hook.** Through the existing hook-call helper, chain SessionStart,
  UserPromptSubmit and PostToolUse payloads and check:
  - no Knowledge in SessionStart on Pi and Copilot, fresh and resumed;
  - tool calls on Pi, Copilot and Claude Code deliver up to the full allowance, each card once,
    by path, by bare file name and by contract symbol;
  - prompts naming a covered file deliver on Hermes Agent and Factory Droid, prompts naming only
    a symbol do not, and prompts deliver nothing on Claude Code, Pi and Copilot;
  - a Copilot session whose state was seeded as an older version left it (startup cards given)
    receives nothing on resume and then gets those cards from tool calls, within the full
    allowance;
  - `knowledge=off` and shadow deliver nothing at any trigger;
  - the micro-skills facts block is still in SessionStart, fresh and on Copilot resume.
- **Second seam: settings.** Through the config load, write and unset functions and the `te
  config` command: retired keys in a file or the environment load without error and change
  nothing; `set` refuses them with the message; `unset` removes them; `show` omits them.
- **Prior art.** The existing Knowledge-injection test module (rewrite its mode matrix into the
  single behaviour), the Knowledge read and prompt helpers, the live-hooks fixtures, the Copilot
  Knowledge resume test, and the Hermes and Droid hook tests for prompt payloads.
- **Recorded sessions.** Replay one recorded Pi session and one Copilot session through the hook
  and confirm Knowledge appears only after tool calls naming covered files.
- Run `python -m pytest tests experiments/tests`.

## Out of Scope

- Micro-skills: their session-start injection, budget (ADR 0001) and resume behaviour.
- Raising or retuning the Knowledge Allowance limits.
- The state lock: a fold holding the mechanisms lock longer than a hook waits still skips that
  call's Knowledge. Separate issue.
- A session pinned to a checkout that no longer exists makes the fold spawn at the end of session
  start raise and discard the whole hook answer, micro-skills included. Separate issue.
- The local benchmark script reusing probe session ids across runs. Not part of this repository.
- Measuring the prompt trigger or Copilot; the benchmark covered Pi only.

## Further Notes

- Decision record: ADR 0002 (Knowledge is given where a mention names it, never at session
  start); glossary terms Knowledge Signal, Relevant Knowledge and Knowledge Allowance.
- Branch: `knowledge-tools-only`, based on `spec-341-integration` at the commit that introduced
  `knowledge_injection`.
- The benchmark's per-run outputs stay outside the repository, per the repository's rule on run
  outputs.
