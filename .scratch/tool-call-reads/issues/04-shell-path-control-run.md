# 04: The shell path gets a card — control run on the real campaign

**What to build:** two Pi sessions on the campaign's subject A (how CodeTour loads and validates a Tour, then records its progress), one with `--memory=off` and one with `--memory=knowledge`, run in the existing campaign harness with the same frozen sources, model and probe, and an answer to one question: does a shell-only exploration now receive the card where the 27 November runs 01 and 07 received none? The control reports, for the knowledge arm, the injections actually recorded with their trigger and signal, whether the card's content shows up in the generated Tour on a file the session never opened with a reading tool, and the token totals of both arms side by side with the earlier ones. A run that receives nothing is a result, not a failure: the ticket delivers the measurement, and the campaign report gains a section either way.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Both sessions run in the campaign harness with the same frozen sources, model and probe as the 27 November campaign, and their artifacts land under it
- [ ] For the knowledge arm, the injections are read from the event log and each one is named with its trigger, its signal and the call that caused it
- [ ] The report says plainly whether a card arrived on the shell path, with the trace line that proves it, or that none arrived and why
- [ ] Token totals of both arms are reported beside the earlier pairs, and the report states whether the comparison is usable or not
- [ ] Paid model calls are counted, and no source, Tour or campaign artifact is overwritten

## Comments

- 2026-11-27: the closing loop of `.scratch/tool-call-reads/`. The earlier campaign measured shell-only exploration twice (runs 01 and 07) and both arms were blind to Knowledge on that path: 13 injections in total, 10 at session start, 3 after a `read`, none after a `bash` call. This ticket is the only one that spends model budget; the three before it are verifiable offline plus a live session with a stub-free provider.
