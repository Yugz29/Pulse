.PHONY: dev dev-reload mode-dev mode-service test status logs reset help

dev:
	./scripts/dev.sh

dev-reload:
	.venv/bin/python scripts/dev_reload.py

mode-dev:
	./scripts/pulse_mode.sh dev

mode-service:
	./scripts/pulse_mode.sh service

test:
	.venv/bin/python -m pytest tests_v2

status:
	./scripts/status.sh

logs:
	tail -n 20 -F \
		~/.pulse_v2/logs/daemon.log \
		~/.pulse_v2/logs/outbox_worker.log \
		~/.pulse_v2/logs/agent_producers.log

reset:
	./scripts/reset-dev.sh

help:
	@printf '%s\n' \
		'make dev     Lance le daemon et les watchers' \
		'make dev-reload  Lance Pulse avec rechargement automatique' \
		'make mode-dev    Bascule en dev (hot reload) — retour service auto en sortie' \
		'make mode-service  Recharge les services launchd (daemon + worker)' \
		'make test    Exécute les tests' \
		'make status  Affiche l’état local de Pulse (daemon, launchd, outbox)' \
		'make logs    Suit les journaux des services launchd' \
		'make reset   Réinitialise la trace de développement' \
		'make help    Affiche cette aide'
