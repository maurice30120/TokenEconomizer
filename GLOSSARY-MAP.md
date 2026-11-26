# Glossary Map

TokenEconomizer has two contexts: what the plugin teaches an agent about a repository, and
what it later reuses as Knowledge. They meet in one proposer call but keep separate languages.

## Contexts

- [Knowledge](./GLOSSARY.md): durable understanding of how the code works, from one or several observed sources, given after a read that covers it or a prompt that names it
- [Micro-skills](./tokeneconomizer/microskills/GLOSSARY.md): facts learned from earlier sessions and injected as a block at session start

## Relationships

- **Micro-skills ↔ Knowledge**: one proposer call may return both missions' lists, each with its
  own candidate limit and validator; a Knowledge is never a Fact, and the injected block carries
  Facts only.
- **Micro-skills → Knowledge**: a read the block made unnecessary is a session that reads less,
  so the same session offers fewer Knowledge Observations.
