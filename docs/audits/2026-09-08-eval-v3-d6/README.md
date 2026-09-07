# Eval MLX, prompt v3 corrigé pour D6 — 8 septembre 2026 (00:11)

Passage `pulse-intel eval --provider mlx` sur les 14 entrées du corpus avec le
prompt v3 après la retouche D6 (consigne « un commit ne liste pas ses
fichiers », définition d'`observed` et exemple réécrits) et la règle de
rejet correspondante du validateur (un point `observed` qui affirme qu'un
fichier n'est pas commité est rejeté dès que la session montre un commit).
Même modèle, mêmes conditions que
[`2026-09-07-validation-open-v3.md`](../2026-09-07-validation-open-v3.md)
(`Qwen3.8-27B-4bit`, argmax, plafond 30 000, `TZ=Europe/Paris`), sorties
écrites hors de l'arbre observé puis copiées ici (`outputs/`, `run.log`).

**12/14 valides, 2 rejets** (`247f2062`, 1 commit ; `eef4956b`, 5 commits) :
le modèle y écrit encore « les modifications sur … ne sont pas committées »,
et le validateur refuse la note. Gabarit D6 dans les sorties valides : 2,
toutes deux sur des sessions **sans aucun commit** (`071bbd62`, `7bbaca78`),
où c'est un fait ; la veille, 9 sorties sur 14 le portaient. Les trois
sessions à commits qui le portaient rendent désormais `[]` (`3cabaefb`,
`cda6ccce`, `eb652ce9`, cette dernière passant de cinq points D6 à zéro).
Attentes annotées : 2/4 (3/4 la veille) — `eef4956b` rejetée, `1e420dda`
inchangée (PR #28 en `carried_over`, écart connu). Coût : +160 à +170
tokens d'entrée par session (prompt), la plus grosse à 23 013, marge 1,30×.
