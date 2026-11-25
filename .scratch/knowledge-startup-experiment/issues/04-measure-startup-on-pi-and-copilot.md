# 04: Measure startup Knowledge on Pi and Copilot CLI

**What to build:** Compare whether giving Knowledge at startup saves reads and tokens while preserving answer correctness on the main agents in Pi and Copilot CLI.

**Blocked by:** 01 (Propose up to eight mixed candidates), 03 (Deliver Knowledge alongside native Facts at session start).

**Status:** resolved

- [x] Run the same tasks with startup shares of 0% and 50% on each host. Keep the available Knowledge, total Knowledge budget, eight-candidate cap and after-read delivery comparable across the two conditions.
- [x] Include tasks where a startup card can help and tasks where it is unrelated. Capture which cards are delivered at startup or after reads, the covered file reads, token use, answer correctness, and proposal and admission counts by type.
- [x] Report the outcomes by host and startup share. Distinguish a card being delivered from evidence that the agent saved reads and answered correctly, and note cases where startup capacity displaced a card that could have helped after a read.

## Answer

Completed eight live sessions and a separate proposer calibration. See the [campaign report](../campaign.md) for delivery, reads, token use, correctness, proposal and admission counts, and the limits of the sample.
