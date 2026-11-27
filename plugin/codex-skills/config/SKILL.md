---
name: "config"
description: >
  Show or change TokenEconomizer's settings: turn micro-skills, tool pruning or the loop guard on or off, or tune them, for this repository or (with --global) every repository. Use when the user asks to configure, enable or disable TokenEconomizer, or choose when Knowledge is injected.
---

# TokenEconomizer: config

Run this command in the repository's root directory:

```
"${TOKENECONOMIZER_HOME:-$HOME/.tokeneconomizer}/bin/te" --host codex --cwd "$(pwd)" config ARGS
```

Use `show` as ARGS unless the user asked to change a setting; then `set KEY=VALUE ...` or `unset KEY ...`, adding `--global` only if they asked for every repository. Show the output verbatim in a code block; if a setting was rejected, say why in one sentence.

Changing a setting (`set`, `unset`) writes TokenEconomizer's own state under `~/.tokeneconomizer`, outside the workspace, which the sandbox keeps read-only: run that command with `sandbox_permissions` set to `"require_escalated"` and a one-line `justification`, so that Codex asks the user to approve it. `show` reads only and needs no approval.

The command reads and writes only TokenEconomizer's own state (under `~/.tokeneconomizer`); it
makes no model call. If it reports that the launcher does not exist, the plugin has not run in a session yet:
ask the user to start a new Codex session in this repository first.

## Knowledge injection

When the user chooses where to inject Knowledge, map their choice to one setting:

| User choice | ARGS |
| --- | --- |
| Session start only | `set knowledge_injection=startup` |
| Tool calls only | `set knowledge_injection=tools` |
| Both | `set knowledge_injection=both` |

Knowledge must also be enabled with `knowledge=on`. Read `config show` first; include
`knowledge=on` in the same `set` command when the user asks to enable injection.
`knowledge=off` remains the switch to disable it. `both` is the default mode.

`startup` makes the full Knowledge allowance available at session start. `tools` injects
after a successful call naming a covered file or symbol, so it cannot help that same call.
`both` shares the allowance without duplicates; only this mode uses
`knowledge_startup_share` (default `0.5`). Setting that share to `1` does not disable tool
injection: use `startup` for that choice.

Check the target agent: Pi and Copilot CLI support startup and tool injection; Claude Code
supports tool injection and retains its prompt trigger in `both`. Other hosts may lack
these delivery points. Codex currently supports neither Knowledge delivery point; changing
its setting does not add hook support. Target the user's actual agent with `--host` when
configuring another agent, and explain unsupported delivery instead of promising injection.

Settings apply on subsequent hooks; already delivered cards stay in context. Use a new
session when the user wants a clean comparison. `TE_KNOWLEDGE_INJECTION` overrides the
saved setting, so check it if `config show` differs from the requested value.
