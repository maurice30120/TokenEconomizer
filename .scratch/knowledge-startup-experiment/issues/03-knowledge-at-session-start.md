# 03: Deliver Knowledge alongside native Facts at session start

**What to build:** Give the main agent on Pi and Copilot CLI eligible Knowledge alongside native Facts at startup, within a configurable share of the Knowledge budget. Keep any unused capacity for Relevant Knowledge after reads.

**Blocked by:** 02 (Give Knowledge its own budget after reads).

**Status:** resolved

- [x] With Knowledge enabled, the existing session-start hook delivers complete cards that pass the current contract and eligibility gates, ordered by descending firing rate and then registration order.
- [x] The startup share uses the existing TE configuration surface and defaults to 50% for the experiment. Apply the share to both Knowledge limits, rounding each down. At 0%, startup delivers no Knowledge and all capacity remains available after reads.
- [x] Cards delivered at startup reduce the allowance available after reads. A read of a covered file does not repeat or recharge a card already in context. Resume keeps the card and its charge when the host retains it, and the session reset behavior also applies to startup cards.
- [x] Verify through the Pi and Copilot session hooks that the card reaches the main agent, delivery can be distinguished by trigger, and subsequent reads use the remaining allowance. Preserve the current per-host subagent behavior and existing Knowledge controls.

## Answer

Verified through the session hooks and the installed Pi and Copilot CLIs. The startup share limits both cards and tokens, and later reads use the balance. A repeated SessionStart event is deduplicated for both native Facts and Knowledge. Copilot restores eligible cards on resume through the same hook without charging them again.
