Status: ready-for-agent

## Problem Statement

Knowledge is currently injected into a session at start, in registration order and without regard to what the agent is doing. A Knowledge about one file can fill the budget of a session that never touches that file, while a relevant one is left out. The campaign report could not show that any Knowledge helped, and the injection log left its injection field empty. Giving the agent Knowledge unrelated to its session is unacceptable.

## Solution

Knowledge is given to the agent only when it is Relevant Knowledge. A Knowledge Signal is the symbol the Knowledge is about or, failing that, its file, taken from the Knowledge's contract. Knowledge is injected when the user's request shares a Knowledge Signal, or when the agent reads a file a Knowledge covers. Nothing is injected at session start. When nothing is relevant, or the host cannot deliver the context to the model, nothing is injected. Each injection is logged with the Knowledge and the signal that triggered it, so the interest of Knowledge can be measured as soon as possible.

## User Stories

1. As a developer, I want only Knowledge related to my request injected, so that my context is not filled with unrelated facts.
2. As a developer, I want a request that names a file or symbol to bring the Knowledge about it, so that the agent starts with what TE already learned.
3. As a developer, I want Knowledge injected when the agent reads a covered file, so that it helps even when my request does not name the file.
4. As a developer, I want no injection when nothing is relevant, so that I do not pay tokens for nothing.
5. As a developer with 100 Knowledges, I want only the matching ones considered, so that the store size does not change the cost of a session.
6. As a developer, I want a Knowledge injected at most once per session, so that the same tokens are not paid at every prompt.
7. As a developer, I want a Knowledge injected again after a clear or compact, so that it is not lost when the context is.
8. As a developer, I want the shared fact and token budget respected, so that Knowledge does not crowd out native facts.
9. As a developer, I want matching Knowledge ranked by strength of match and then firing rate, so that the most relevant fits the budget first.
10. As a developer, I want a Knowledge with an invalid proof, a forgotten one or one not yet eligible by lifecycle never injected, as today.
11. As a developer using a host that does not pass hook context to the model, I want no Knowledge injected there, so that nothing is promised that the agent cannot receive.
12. As a developer, I want existing Knowledge to work without relearning, so that the change gives immediate results.
13. As a campaign analyst, I want every injection logged with the Knowledge identity and the signal that triggered it, so that I can prove what the agent was given and why.
14. As a campaign analyst, I want to see when the covered file had already been read before the injection, so that I can tell when the Knowledge came too late to save a read.
15. As a campaign analyst, I want the injection log to stop being empty, so that the transcript is no longer the only evidence.
16. As a maintainer, I want unmatched Knowledge to stay stored and visible in `te microskills`, so that inspection and forgetting still work.
17. As a maintainer, I want no model call in the selection, so that it adds no cost or latency to a prompt.
18. As a maintainer, I want hooks to keep failing open, so that a selection error never blocks a session.

## Implementation Decisions

- Scope is Knowledge only. Native Facts and micro-skills keep their current behaviour and injection at session start.
- A Knowledge Signal is derived from the Knowledge's contract: the symbol when it has one, otherwise the file. No free keywords are added. Existing stored Knowledge gets its signal from its current contract; no migration of learned state is needed and the on-disk names stay compatible.
- Matching is deterministic and local: a request shares a signal when it names the symbol or the file (by path or file name). A Knowledge with no shared signal is not relevant.
- Two triggers: the user prompt hook and the agent's read of a covered file. The second delivers the context after a tool call, which each host must be verified to accept.
- The session-start Knowledge injection is removed. Knowledge is never given outside the two triggers.
- A host whose hook output does not reach the model gets no Knowledge injection, rather than falling back to session start. The existing per-host capability for prompt context is the gate; the tool-call trigger needs its own verified per-host capability.
- Each Knowledge is injected at most once per session; a clear or compact makes it eligible again. Resumed sessions that already carry the context are not injected twice.
- The configured shared budget (maximum facts and approximate tokens, shared with native facts) is kept. Candidates are ranked by strength of match, then firing rate, replacing registration order.
- Proof validation, lifecycle gates and the firing gate are unchanged: only Knowledge that is injectable today and relevant is injected. Hashing the current file before injection stays.
- The injection log records, for each injection, the Knowledge identity and the signal that triggered it. When the covered file was read earlier in the session, the log says so.
- Full-content Knowledge loaded on demand is out of scope; the short injected fact stays.
- Glossary: Knowledge Signal and Relevant Knowledge are defined in the TokenEconomizer glossary and must be used as written.

- An injection must leave the cached prefix of the next request unchanged on every host. Context added at the end of the conversation is expected to satisfy this; Pi, which places context in its system prompt section, needs a specific check and an alternative delivery if a varying injection would rewrite that section.

## Testing Decisions

- A good test checks only what the hooks emit and log for a given stored state and event, never the matching or ranking internals.
- A single seam: the live hooks, as the existing recorded-session tests already do (sanitized Pi and Copilot recordings, simulated model provider, no overridden lifecycle thresholds).
- Cases: a prompt naming the symbol or file injects; a read of a covered file injects; no shared signal injects nothing; once per session and again after clear or compact; a host without prompt context injects nothing; budget and ranking by observable result; invalid proof, forgotten and ineligible Knowledge never injected; the log carries the identity and signal and flags a prior read; a selection error leaves the hook output empty.
- Prior art: the recorded Pi active-session learning test, the Copilot recording test and the workflow tests for budget, native coexistence and user controls.

## Out of Scope

- Native Facts and micro-skills selection.
- Full Knowledge content loaded on demand, a Knowledge catalogue or a tool the model calls.
- Semantic or model-based relevance, and free keywords as signals.
- Changing how Knowledge is learned, proposed, confirmed or retired.
- The other campaign findings: old log errors, restored Tours and calibration counted in cadence.

## Further Notes

- The aim is to test the interest of Knowledge as fast as possible; the log of injections and prior reads is how the next campaign will tell whether it saved work.
- Knowledge is untrusted data; a valid proof does not make the fact correct.
- Which hosts accept context after a tool call is to be verified during implementation.
