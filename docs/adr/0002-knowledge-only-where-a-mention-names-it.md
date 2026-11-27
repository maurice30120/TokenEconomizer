# Knowledge is given where a mention names it, never at session start

Relevant Knowledge reaches the agent only right after a tool call names its signal, or — on an
agent that cannot receive context after a tool call — after the user's request names its file.
Nothing is given at session start, and the `knowledge_injection` setting and its startup share go
away. A local benchmark on Pi (2026-11-27, three runs per variant, blind evaluation) compared
startup, tool-call and both: the tool-call variant was judged best and cost least, and giving both
cost the most without judging better. Knowledge given when the agent reaches the code it covers
is read in context; a startup block is paid for before anyone knows it is needed.

Micro-skills are not concerned: their facts are still injected at session start (ADR 0001).

## Considered Options

- **Keep the three modes, default to `tools`** — rejected: a mode nobody runs keeps the startup
  share, the Copilot resume restoration and a second path through the state lock, for no measured
  benefit.
- **Keep the prompt trigger everywhere** — rejected where tool calls can carry Knowledge: two
  triggers in one session reproduce the `both` variant. It stays only where tool calls cannot,
  so those agents keep their one path to Knowledge, and it matches files only: a symbol named
  alone in a request is no mention.

## Consequences

- The tool-call trigger is unchanged from the measured variant, symbols included, and has the
  whole Knowledge Allowance.
- A session resumed after the change no longer restores startup Knowledge; what it had been given
  at start becomes eligible again.
- The benchmark measured Pi only; Copilot's startup restoration and the prompt trigger were not
  measured.
