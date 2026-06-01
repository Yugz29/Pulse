# Decisions

Ce dossier contient les décisions d'architecture ou de phase.

Une décision décrit ce qui est autorisé, interdit ou accepté temporairement à un moment donné. Les décisions doivent rester alignées avec les contrats actifs.

Si une décision contredit un contrat, le contrat gagne sauf revalidation explicite du contrat. Si une décision plus récente contredit une ancienne, la décision récente doit signaler explicitement la priorité.

## Sommaire

- `core-reset-foundation-closure.md` — clôture C2 hardening Core.
- `architecture-cleanup-plan.md` — plan C4 de cleanup architectural progressif.
- `route-surfaces-closure.md` — clôture C4a route registration / surface boundaries.
- `boot-safety-closure.md` — clôture C4b main.py boot safety minimal.
- `service-lifecycle-closure.md` — clôture C4c du lifecycle services/workers Core / Lab.
- `today-value-loop.md` — décision de boucle de valeur minimale “Aujourd'hui”, validée en dogfooding initial et utilisée pour cadrer l'observation / stabilisation.
- `product-debug-lab-ui-split.md` — décision UI pour séparer les surfaces Produit, Debug / Lab et Encoche.
