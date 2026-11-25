# Knowledge alongside native micro-skills

Status: ready-for-agent

## Problem Statement

A Knowledge can explain how several files work together, but the agent currently receives it only after reading a covered file. That can save later reads, while the triggering read has already happened. Native Facts arrive earlier, at session start, and currently use part of the budget that determines whether Knowledge can be delivered after a read. At proposal time, the shared four-candidate cap may also leave little room for Knowledge.

We want to find out whether giving the agent some Knowledge at session start can save reads and tokens while preserving answer quality. Earlier startup injection could spend context on cards unrelated to the task, so the experiment needs a configurable limit and a read-triggered fallback.

## Solution

Use the same session-start hook for native Facts and selected Knowledge, and keep delivering Relevant Knowledge after a successful read of a covered file. Knowledge has its own configurable budget across the conversation context. By default, startup can use up to half of both its card and token limits, leaving the rest for reads. A card appears once while it remains in context.

When the existing shared proposer can propose both kinds, let it return up to eight mixed candidates without quotas. Keep the existing evidence and lifecycle checks. Compare startup shares of 0% and 50% on equivalent tasks in Pi and Copilot CLI.

## User Stories

1. As an agent, I want a Knowledge to explain the relationships within one mechanism across at least two files, so that reading one source can give me a useful view of the others.
2. As an agent, I want selected cards at startup alongside native Facts, so that I may answer without making an initial read.
3. As an agent, I want a successful read of any covered file to surface the full relevant card, so that Knowledge remains useful during exploration.
4. As an agent, I want several Knowledge entries to be able to cover the same file, so that separate mechanisms stay understandable.
5. As an agent, I want each card delivered only once while it remains in my context, so that a later read does not repeat startup context or spend the budget twice.
6. As an agent, I want cards to be eligible again when a clear or compaction removes them from context, so that useful Knowledge can return.
7. As a developer, I want a configurable Knowledge budget independent of native Facts, so that a full native budget does not prevent eligible cards from reaching the agent.
8. As a developer, I want startup and read delivery to draw on the same allowance, so that I can bound the total cost of Knowledge in context.
9. As a developer, I want to configure how much of both the card and token limits startup can use, so that early delivery leaves room for cards tied to later reads.
10. As a developer, I want unused startup capacity available after reads, so that a small startup injection does not waste budget.
11. As an agent, I want complete eligible cards within the remaining budget, so that I receive the relationships and roles together.
12. As a developer, I want Knowledge to continue honoring the existing file or symbol contracts, so that a card with stale evidence is withheld.
13. As a developer, I want the shared proposer to have up to eight slots across both types, so that Knowledge has more opportunity to appear without a mandated split.
14. As a developer, I want to continue managing both types through the micro-skills commands and activating Knowledge through its existing switch, so that the experiment fits the current workflow.
15. As a campaign analyst, I want proposal and admission counts by type, so that I can see whether Knowledge gets room in the shared call.
16. As a campaign analyst, I want comparable Pi and Copilot runs with and without startup delivery, so that I can assess reads, tokens and answer correctness.
17. As a campaign analyst, I want to know which card arrived and when, so that I can relate delivery to subsequent reads and answers.

## Implementation Decisions

- Reuse the existing proposal cadence and shared model call where it already applies. Increase the shared cap from four to eight across the model request and response processing. Preserve the model's ordering and the checks for each candidate type. Use no type quotas and make no automatic replacement call for rejected candidates.
- Keep the current Knowledge contract and revalidate it before delivery from either trigger. A Knowledge describes a coherent mechanism between at least two distinct source files. Knowledge Evidence remains scoped to the recorded file or symbol and to what the Knowledge Observation supports. Keep the existing admission, lifecycle and forgotten gates.
- Use the existing session-start and read hooks. Choose startup cards locally in descending firing rate, then registration order. After a successful read, select Relevant Knowledge using the existing exact-path Knowledge Signal match and ordering. The optional symbol still determines proof granularity.
- Keep the native Fact budget. Configure a dedicated Knowledge card limit, approximate token limit and startup share through TE's existing configuration surface. Apply the startup share to both limits, round down and default the share to 50% for the experiment. At 0%, all Knowledge capacity is available after reads.
- Account for cards and tokens across both triggers while the cards remain in context. Skip a card that cannot fit in full and consider subsequent eligible cards. A resumed context that already contains a card keeps its charge and receives no duplicate. A clear or compaction that removes cards makes their capacity available again.
- Keep Knowledge separately enabled through the existing switch and manageable through the existing micro-skills commands. Preserve the current per-host handling of subagents.

## Testing Decisions

- Verify observable behavior at the existing session hooks and fold workflow. Reuse the recorded Pi and Copilot sessions, simulated proposer and existing tests for after-read delivery, Knowledge contracts, shared proposals, resume and user controls.
- Verify one shared call can submit a mixed batch of up to eight candidates, with validation applied by type and ninth or later candidates outside the cap.
- Verify startup plus read delivery on both hosts. Exercise both limits, rounding, the 0% setting, unused startup capacity, independent native Fact capacity, full-card fit and ordering. Check that invalid, forgotten and ineligible cards are withheld, that a later read cannot duplicate or recharge a startup card, and that resume and context reset preserve the intended behavior.
- Run the same tasks on the main agents of Pi and Copilot CLI at 0% and 50%. Keep the available Knowledge, total budget, proposal cap and read trigger comparable. Record proposal and admission counts by type, Knowledge delivery, covered file reads, token use and answer quality. Include tasks where the startup card is useful and tasks where it is unrelated.

## Out of Scope

- New tools, an MCP server, a Knowledge catalogue, and explicit lookups.
- A separate first-message trigger, a new relevance model, or a model call to select cards for injection.
- Changes to the file or symbol evidence contract, native Fact behavior, or subagent behavior. The experiment does not require separate subagent validation.
- Quotas by candidate type or a comparison of four versus eight candidates.

## Further Notes

An injection records that the card reached the agent. The answer and subsequent tool calls are the evidence for whether delivery saved work while preserving correctness. The triggering read can only be saved when the card is already available, for example at startup.
