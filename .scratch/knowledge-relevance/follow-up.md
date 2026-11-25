# Knowledge after a covered read

Reading one source of a mechanism should give the agent enough context to avoid some later reads. For example, reading `user.ts` can surface a card explaining how it interacts with `connection.ts` and `right.ts`. The agent can still read either source when the task requires more detail or verification.

## Proposal and validation

- Keep the native micro-skills proposal cadence. When both types can be proposed together, use the shared model call and allow up to eight total candidates in the experiment. The model can mix native facts and Knowledge freely. Observe how many of each type are proposed and admitted to see whether Knowledge gets space in practice.
- A Knowledge describes the relationships within one mechanism spanning at least two distinct files. Different mechanisms can cover the same file. Each candidate must pass the existing file or symbol contract, admission rules, and lifecycle checks.

## Delivery and controls

- At session start, present selected, eligible Knowledge cards to the agent alongside native micro-skills. A successful read of any covered file can also deliver the full card. If the card is already in the conversation context, another read must not duplicate it. A clear or compaction can make the card eligible again when it has left the context.
- Keep the native micro-skills budget at session start. Give the conversation context a dedicated Knowledge budget, configurable through the same TE configuration as the native micro-skills budget. Cards delivered at session start and after reads draw from the same allowance. Skip cards that cannot fit in full within the remaining budget.
- Make the share of the Knowledge budget available at session start configurable, with half as the default for the experiment. Apply that share to both the maximum card count and the approximate token limit, rounding each startup limit down. Any budget unused at startup stays available after reads. Select eligible startup cards using the existing Knowledge order: descending firing rate, then registration order.
- Keep `knowledge=on` as a separate switch and use `te microskills`, `forget`, and `unforget` to manage both types. Use the existing session-start and read hooks to deliver cards.
- Apply the existing TE behavior for subagents on each host. Validate the experiment on the main agents in Pi and Copilot CLI.

## Experiment outcome

On Pi and Copilot CLI, run the same tasks with a startup share of 0% and 50%. Keep the total Knowledge budget, the eight-candidate proposal cap, and after-read injection the same. Check whether agents answer correctly with fewer reads of the covered sources and fewer tokens. Use the injection log and tool trace to establish whether a card reached the agent before those reads. An injection establishes delivery. The answer and the subsequent actions provide separate evidence of usefulness.
