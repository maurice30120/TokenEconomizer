# 02: Give Knowledge its own budget after reads

**What to build:** Give Knowledge a configurable card limit and approximate token limit for the conversation context. A successful read can deliver a full card using this allowance even when native Facts used their entire startup budget.

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] Both Knowledge limits use the existing TE configuration surface. Native Facts keep their own budget and do not consume the Knowledge allowance.
- [x] Successive reads of covered files draw from the same remaining card and token limits. A card too large to fit in full is skipped, and the next eligible card can still fit.
- [x] A card already in context is neither repeated nor charged again. Resume preserves the allowance already used when the context still contains those cards. A clear or compaction that removes the cards makes their capacity available again.
- [x] The read hook keeps its existing Knowledge Signal matching, ordering, evidence validation and eligibility gates. Verify delivery and accounting across multiple reads using the existing hook tests.

## Answer

Verified on both host adapters across successive reads, resume, and context reset. The dedicated card and token limits remain available even when native Facts fill their budget. Pi failed reads are rejected, and Pi compaction releases the charges for dropped read messages while keeping retained cards.
