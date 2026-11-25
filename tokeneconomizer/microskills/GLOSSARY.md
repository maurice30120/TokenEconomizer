# TokenEconomizer Micro-skills

This context describes the facts a session is given about its repository, before it has read
anything: what they are, how they earn their place, and what the agent actually receives.

## Language

**Fact**:
A claim about this repository that the plugin learned from earlier sessions and may inject, with
the evidence shape that shows it still applies. A Fact is not Knowledge: it describes a habit or
a shape of work, never the relationships inside a mechanism.

**Native Fact**:
A Fact the paid proposer authored from earlier sessions, with its own injection line and the evidence shape that keeps it honest.
_Avoid_: manual fact, micro-skill, learned fact

**Environment Fact**:
A Fact the free layer derives from a recurring failure of the environment itself (a missing
command, a missing dependency, a command written in a form that does not work here), with no
model call.
_Avoid_: envfact, free fact, system fact

**Injected Block**:
The text a session receives at start: one header, then one line per Fact the block carries.
_Avoid_: prefix, micro-skills block, injected manual, context block

**Block Budget**:
The caps on the Injected Block — how many lines and how many tokens — shared by every layer that
composes it. A line that does not fit is left out whole; the next candidate is still tried.
_Avoid_: per-layer budget, micro-skills limit

**Injection Credit**:
The rule that a Fact the session was actually given, whose waste did not occur, counts as having
fired: the block did the work, and the Fact must not lose its rate for succeeding.
_Avoid_: prevention credit, seeded firing

**Firing Gate**:
The condition a Fact must clear to enter the Injected Block: it is `ACTIVE`, and the waste it prevents has occurred often enough on the sessions that exercised it. Being `ACTIVE` is not enough, and "injected" means nothing weaker than passing this gate.
_Avoid_: injection threshold, firing rate gate

**Micro-skills**:
The mechanism that learns Facts and injects the Injected Block, both layers together. It is never the content: the content is Facts.
_Avoid_: micro-skills meaning the Facts themselves, injection layer
