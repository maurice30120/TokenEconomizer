# 03: The record and the docs say what the tool trigger now means

**What to build:** nothing in the record may claim a read that did not happen. The per-session list that today means "files this session read" means "files this session named", keeps its cap and its role in `read_before`; the injection event records the trigger truthfully for a call that was not a read, and the value that today reads `after_read` stops asserting one; the delivery key the host uses to place the block after a specific tool result is untouched. The Knowledge documentation's trigger section states the rule the code now follows — the mention of a Signal in the call, whatever the tool, a search that names a file counting as much as a full read — together with the limits that stay: the card cannot credit the read it followed, a mention outside the workspace is ignored, a card already given is not given again, and the shared budget is the only cap. `te microskills` and the event log remain the two places to look, and the doc says so in one line.

**Blocked by:** 02

**Status:** implemented

- [x] The session list is named and documented for what it holds; its cap, its reset on clear and its use by `read_before` are unchanged
- [x] The injection event names the trigger truthfully for a non-read call, and a reader of the log can tell a full read from a search without guessing
- [x] The block is still delivered after the right tool result (the existing delivery key keeps working; no regression on Pi)
- [x] The Knowledge documentation's trigger section describes the mention rule, the exclusions, and the four limits that remain
- [x] The glossary names the trigger if it names triggers at all
- [x] An existing state file whose list holds a pre-change session still loads and is read as it was

## Comments

- 2026-11-27: split from 02 because the code change and the meaning of the recorded evidence are reviewed differently, and because the campaign reads these fields to decide whether an injection happened at all (see the ledger finding in `rapport-campagne-knowledge-pi-20261127.md`: the ledger row still reports `injected_chars: 0` for a session that received two cards, because that field covers native facts only).
- 2026-11-27: done. The session list is now `files_named` (cap 500, reset on clear, role in `read_before` unchanged); a pre-change state that holds `files_read` is read as it was and migrated on the next write (`_named_files`, `_knowledge_from_tool` in `tokeneconomizer/plugin/controller.py`; pinned by `test_the_session_list_says_named_and_an_older_files_read_state_still_loads`). The injection event now says what happened: `trigger: "tool"` for every tool-call trigger, plus `tool` (the tool that named the file, `read` vs `bash` telling a full read from a search) and `when: "after_call"` instead of the false `after_read`. Delivery is untouched (`hookSpecificOutput.hookEventName == "PostToolUse"`, the same key the host places after the result). The controller's read-named methods are renamed (`knowledge_on_tool`, `_reports_named`, `_knowledge_from_tool`); the Pi compaction bookkeeping keys (`knowledge_read_blocks`, `retained_knowledge_reads`) are left as they are — internal bookkeeping, not the record, and renaming would touch the Pi extension. The Knowledge README's trigger section now states the mention rule, the exclusions, and the four limits (cannot credit the call it followed; a mention outside the workspace is ignored; a card already given is not given again; the shared budget is the only cap), and one line names the two places to look (`te microskills`, the event log). The glossary's Knowledge Signal and Relevant Knowledge entries name the trigger.
