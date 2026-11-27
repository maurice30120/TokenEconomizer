# 02: A tool call that names a Knowledge Signal receives it

**What to build:** on a host whose context follows the tool result (Claude Code, Pi, Copilot), any tool call whose text names a Knowledge Signal — its symbol as a whole identifier, its path, or its bare file name — brings the Relevant Knowledge covering it into the session after the result, whatever the tool: a shell `grep`, `rg`, `sed`, `cat` or `git diff` naming the file, an edit or a write naming it, a host tool with its own name for reading. A call that names nothing covered injects nothing. Nothing else about admission changes: the Knowledge Contract is re-checked, lifecycle and firing gates apply, a forgotten card stays forgotten, a shadow run and a replayed hook and a sub-agent call still inject nothing, a failed call gives nothing, and a card already given in this session is never given twice — the shared card and token budget, startup share included, is the only cap. The block still lands after the tool result without rewriting the cached prefix.

**Blocked by:** 01

**Status:** implemented

- [x] On Pi, a `bash` call naming a covered file gives that file's Knowledge after the result — the exact shape that gave nothing in the campaign (`grep -n … storage.ts`, `sed -n … storage.ts`, `cat … storage.ts`)
- [x] A write or an edit naming a covered file gives it too: the rule is the mention, not the shape of the command
- [x] A call naming nothing covered, a failed call, a sub-agent call and a replayed hook inject nothing
- [x] A card already given in the session is not given again, and the budget and startup share stop the selection where they stop it today
- [x] An invalid Contract, a retired or forgotten card is still excluded
- [ ] Verified in a live Pi session whose exploration is shell-only, and asserted by tests over a table of real call payloads taken from the campaign traces
- [x] An exception anywhere in the path leaves the hook output empty and the session unaffected

## Comments

- 2026-11-27: the rule the owner asked for — "if we see a file name, we inject, whatever the command". It deliberately replaces command-shape filtering (`cat` yes, `grep` no). Consequences accepted: a `cat > file` write over a covered file and an `ls` naming it both inject, and a search showing three lines of a file injects as readily as a full read. The stale-card risk that follows is covered by the Contract check at injection time, not by the trigger.
- 2026-11-27: done. `Host.named_files` now matches the call's own text — the tool name and its argument values, never the result, never a parsed command — against `Knowledge.nameable()`, ranked by `match_strength`; the one mention whose location is known without parsing, a file-reading tool's path, still resolves against the workspace so a read outside it names nothing. The gate `_reports_read` passes the nameable signals and fails open on an unreadable state; the recorder keeps every named file, the injection goes to the strongest. Delivery, budget, startup share, contract, lifecycle, forgotten, shadow, sub-agent and replay gates are untouched (`_inject_knowledge`, `covering`). Tests: a seam table over the campaign's own shapes (the real run-01/07 `wc -l … storage.ts` trace line included), the trigger end to end on Pi for `bash`/`write`/`edit`, and the nothing-cases (`tests/test_knowledge_tool_files.py`). One accepted consequence, not yet pinned in the doc: a call naming several covered files injects for the strongest mention only. The live Pi verification (checkbox) is the 04 control run's knowledge arm. Log fields still say `trigger=read`, `when=after_read` — 03 makes them truthful.
- 2026-11-27: follow-up corrects the earlier strongest-file-only behavior: all named files are considered in match order, deduplicated under one budget and one Pi block. The live control logged two cards after a bash call; the source exploration used bash, although three skill references were read using `read`. The checkbox remains open because the full session was not exclusively shell-only. Failed calls with nonzero exit status are excluded.
