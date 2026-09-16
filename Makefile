# Pulse — cibles de la racine. Core et Intelligence ont leur propre Makefile.

.PHONY: hooks test-hooks

# Nom sous lequel le wrapper gstack de .git/hooks/pre-push chaîne un hook local.
GSTACK_LOCAL_HOOK := pre-push.local
HOOK_SOURCE := scripts/hooks/prepush_local.sh

# Installe le second étage du hook de pré-poussée ($(HOOK_SOURCE)) comme hook
# local de gstack, dans le répertoire de hooks du dépôt, hors versionnement.
hooks:
	@dir="$$(git rev-parse --git-path hooks)"; dest="$$dir/$(GSTACK_LOCAL_HOOK)"; \
	install -m 755 $(HOOK_SOURCE) "$$dest"; \
	echo "installé : $$dest"; \
	if ! grep -qs "$(GSTACK_LOCAL_HOOK)" "$$dir/pre-push"; then \
	  echo "attention : $$dir/pre-push n'est pas le wrapper gstack (ou absent) ; le hook local ne sera pas chaîné" >&2; \
	fi

test-hooks:
	bash scripts/hooks/test_prepush_local.sh
