# 02: Inject a Knowledge once per session

**What to build:** a Knowledge already given to the agent in a session is not given again at later prompts. After a clear or compact, which drop the context, it becomes eligible again. A resumed session that already carries the earlier context does not receive it twice. Update the Knowledge documentation.

**Blocked by:** 01

**Status:** resolved

- [x] A second prompt naming the same file or symbol injects nothing new
- [x] After a clear or compact, the Knowledge can be injected again
- [x] A resumed session that keeps its context is not injected twice
- [x] Tested through the live hooks
