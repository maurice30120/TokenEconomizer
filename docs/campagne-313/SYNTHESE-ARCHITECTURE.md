# TokenEconomizer — synthèse d'architecture

Rédigée à partir des Tours TE1 à TE6 (titres, descriptions et étapes).

## Principe

TokenEconomizer (TE) est un plugin pour agents de codage. Il apprend des sessions terminées et change ce que coûtent les suivantes, par trois mécanismes : faits injectés (micro-skills et Knowledge), élagage d'outils et garde de boucle (TE6).

## Du hook au mécanisme

Sur Pi, une extension TypeScript est le seul point d'entrée côté agent. Elle convertit chaque événement (par exemple `tool_result`) en charge utile compatible Claude. Elle lance un processus Python éphémère (`scripts/te-hook`, puis `te_bootstrap.py`). `hook.main()` lit stdin et écrit stdout. L'adaptateur d'hôte comble ce que Pi ne fournit pas. `LiveContext.build()` fixe où l'état sera écrit. `LiveController.handle()` route l'événement parmi cinq moments de session. Une file garantit un seul hook à la fois par session (TE1, TE6). Le hook ne doit jamais casser l'agent.

## Cycle de vie d'une session

| Moment | Ce qui se passe |
| --- | --- |
| SessionStart | Injection d'un bloc déjà calculé, sans appel de modèle |
| PostToolUse | Une décision par appel d'outil, jamais bloquante ; alimente la garde |
| SessionEnd | Rend la main tout de suite ; le pli est différé |
| Fold | Une session vaut une tâche, repliée une seule fois : coût, observations, apprentissage |

Le coût de la session est calculé et enregistré dans le pli (TE6).

## Les mécanismes

Un contrat commun, avec quatre hooks et une classe `Stage`, relie tous les mécanismes (TE6).

- **Faits d'environnement (micro-skills).** Six familles apprises sans modèle, plus un proposeur qui doit citer ses preuves. Un fait passe de candidat à actif après trois confirmations. Il est injecté seulement si le gaspillage revient (porte de tir) et dans un budget borné. Il sort par contradiction, décroissance ou oubli (TE2).
- **Knowledge.** Troisième source, optionnelle : des faits adossés à un fichier réellement lu. Une preuve est une empreinte, soit d'un fichier complet, soit d'un symbole (lecture partielle). Elle est calculée au pli et enregistrée dans l'état. Elle est revérifiée juste avant l'injection au SessionStart (TE5).
- **Élagage d'outils.** Le fold reconstitue la preuve de ce qui était chargé et de ce qui a servi. Une proposition n'apparaît qu'avec assez de prompts et de sessions. Elle exclut la surface de travail et les outils protégés. En mode `auto`, elle attend que le dépôt soit calme. Elle s'écrit selon l'hôte : JSON (Claude Code), TOML (Codex), serveur MCP entier (Copilot) (TE3).
- **Garde de boucle.** Cascade en trois étages : backstop dur, porte gratuite et heuristique stricte (churn, bruit et répétition), puis un juge qui ne fait jamais attendre l'agent. Une enveloppe apprise mesure la longueur normale des tours réussis. Une redirection est suivie, si elle ne suffit pas, d'une notice à la personne, jamais d'un arrêt. Sur Pi, la redirection est un message de steering (TE4).

## Limite de cette synthèse

Elle reflète ce que les Tours disent et ce qu'ils ancrent ; seules les ancres ont été vérifiées par un contrôle automatique.
