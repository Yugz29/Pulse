# Decisions

Ce dossier contient les décisions d'architecture ou de phase.

Une décision décrit ce qui est autorisé, interdit ou accepté temporairement à un moment donné. Les décisions doivent rester alignées avec les contrats actifs.

Si une décision contredit un contrat, le contrat gagne sauf revalidation explicite du contrat. Si une décision plus récente contredit une ancienne, la décision récente doit signaler explicitement la priorité.

## Sommaire

- `C2_CLOSURE_DECISIONS.md` — clôture C2 hardening Core.
- `C4_ARCHITECTURE_CLEANUP_PLAN.md` — plan C4 de cleanup architectural progressif.
- `C4A_ROUTE_SURFACES_CLOSURE.md` — clôture C4a route registration / surface boundaries.
- `C4B_BOOT_SAFETY_CLOSURE.md` — clôture C4b main.py boot safety minimal.
- `C4C_SERVICE_LIFECYCLE_CLOSURE.md` — clôture C4c du lifecycle services/workers Core / Lab.
- `TODAY_VALUE_LOOP_PLAN.md` — décision de boucle de valeur minimale “Aujourd'hui” avant reprise C4c.2+.
- `UI_PRODUCT_DEBUG_LAB_SPLIT.md` — décision UI pour séparer les surfaces Produit, Debug / Lab et Encoche.
