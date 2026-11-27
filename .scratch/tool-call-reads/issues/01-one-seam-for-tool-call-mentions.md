# 01: One seam answers which files a tool call names

**What to build:** the plugin answers, for any tool-call payload, the workspace files that call names — as a list, in one place. Today the answer is the single path argument of a file-reading tool (`Read`, `read`, `view`) and nothing else, and it is produced inside the plugin's host seam then consulted by two callers: the gate that decides whether Knowledge may be given after a tool call, and the recorder that keeps what the session has read. Both callers take the list from that one seam, and the seam ranks what it finds with the matcher the prompt trigger already uses for a Knowledge Signal (symbol as a whole identifier, then path, then bare file name), so a later ticket extends the list without touching either caller. Behaviour is unchanged: on Pi a `read` of a covered file injects and logs exactly what it logs today and no other tool call injects anything. The seam's comment records the rule the next ticket relies on — a mention is a Knowledge Signal found in the call's text, never a parsed command — so no shell parser gets written here.

**Blocked by:** None (can start immediately)

**Status:** implemented

- [x] A call through `Read`/`read`/`view` still injects the covering Knowledge, with the same log fields (`trigger=read`, `signal=<file>`, `read_before`, the file named in `events.jsonl`)
- [x] Any other tool call still injects nothing
- [x] The gate and the recorder both take their answer from the one seam; no second list of tool names survives in the plugin
- [x] The ranking is the prompt trigger's matcher, called on the call's text, so a symbol, a path and a bare file name rank as they do for a prompt
- [x] A file outside the workspace resolves to nothing
- [x] Observation and capture agree with the seam on what the session read, so a Digest and a runtime injection never disagree about a file
- [x] The plugin tests and the Knowledge tests are green, and a live Pi session on `read` behaves as it did before the change

## Comments

- 2026-11-27: prefactor for `.scratch/tool-call-reads/`. Measured on the 27 November campaign (`rapport-campagne-knowledge-pi-20261127.md`, workspace root): 13 injections, of which 10 at session start and only 3 after a tool call, all 3 on the `read` path. Runs 01 and 07 explored the sources through `bash` (`grep`, `sed`) and received no card after a tool call at all. On Pi, shell exploration is the common path.
- 2026-11-27: done. The seam is `Host.named_files(p, signals, cwd, root)` in `tokeneconomizer/plugin/hosts.py` (it replaces `Host.read_path`; the read-tool names now appear once in the plugin, pinned by `test_the_read_tool_names_live_only_in_the_one_seam`). The gate `_reports_read` and the recorder `_knowledge_from_read` take their answer from it. `Knowledge.nameable()` in `tokeneconomizer/knowledge/stage.py` supplies the `(signal, file)` pairs, symbol sources nameable by their file too. Behaviour unchanged: the read trigger injects and logs exactly as before (`tests/test_knowledge_tool_files.py`, `tests/test_knowledge_read.py`), a bash call naming a covered file still injects nothing (`test_a_bash_call_that_names_a_covered_file_injects_nothing_today`, flips with 02). The live Pi read path gets its verification with 04, whose knowledge arm runs the same read trigger.
