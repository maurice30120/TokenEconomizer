# Campagne Knowledge au démarrage

Huit sessions sur les agents principaux de Pi et Copilot CLI. Pour chaque hôte, les deux mêmes tâches ont été exécutées à 0 % et 50 % de part au démarrage. Chaque session partait du même état de test avec une micro-skill et une Knowledge valides. Le budget Knowledge total était de quatre cartes et 300 tokens estimés, avec le plafond commun de huit candidats et le déclencheur après lecture dans les deux configurations.

Une tâche demandait le port de développement et le rôle de `service.py` et `defaults.py`. L'autre demandait le titre dans `ui.txt`, hors de la couverture de la carte. Les réponses et lectures ont été vérifiées dans les traces. Les totaux ci-dessous incluent les tokens d'entrée, de lecture et de création du cache, ainsi que les tokens de sortie.

- **Pi** (`deepseek-v4-1-flash-1017`). Tâche couverte : 2 178 tokens à 0 % et 2 264 à 50 %. Les deux fichiers couverts ont été lus dans les deux cas. Tâche hors couverture : 1 915 et 2 059 tokens, avec une lecture de `ui.txt` dans chaque configuration.
- **Copilot CLI** (`gpt-6-luna`). Tâche couverte : 7 418 tokens à 0 % et 11 471 à 50 %. Les deux fichiers couverts ont été lus dans les deux cas. La session à 50 % a également fait un appel de consultation du répertoire. Tâche hors couverture : 7 082 et 7 236 tokens, avec une lecture de `ui.txt` dans chaque configuration.

Les huit réponses étaient correctes. Au démarrage, les traces montrent une occurrence de la micro-skill dans chaque session et une occurrence de la Knowledge dans chaque session à 50 %. À 0 %, la carte a été donnée après une lecture dans les deux tâches couvertes. À 50 %, elle n'a pas été répétée après lecture. Deux appels au hook Copilot pour le même démarrage ont révélé une duplication lors du premier essai. La déduplication commune à la micro-skill et à la Knowledge est vérifiée sur la relance dont les résultats figurent ici.

La campagne n'a montré ni économie de lectures couvertes ni baisse de tokens due au démarrage. Elle comporte une exécution par cellule et une seule carte disponible. On n'a donc pas observé de concurrence entre cartes, ni de carte utile évincée par une carte donnée au démarrage.

Le stock a été gardé fixe pendant la comparaison pour isoler la livraison. Le proposant a été mesuré séparément avec les modèles réels et des traces de lecture contrôlées. Pi a proposé et admis trois micro-skills et n'a proposé aucune Knowledge. Copilot a proposé une Knowledge, qui n'a pas été admise, et aucune micro-skill. Ce petit échantillon établit que le compteur distingue propositions et admissions. La présence de huit places ne garantit aucune proposition de Knowledge.
