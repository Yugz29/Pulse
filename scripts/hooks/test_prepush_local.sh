#!/usr/bin/env bash
# Tests de scripts/hooks/prepush_local.sh avec un faux gstack-redact et un faux gh.
# Lancer : make test-hooks   (ou bash scripts/hooks/test_prepush_local.sh)
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
hook="$here/prepush_local.sh"
work="$(mktemp -d "${TMPDIR:-/tmp}/pulse-prepush-tests.XXXXXX")"
trap 'rm -rf "$work"' EXIT
failures=0

# --- Doubles -------------------------------------------------------------------
mkdir -p "$work/bin"
cat > "$work/bin/gh" <<'GH'
#!/usr/bin/env bash
# Faux gh : la visibilité vient de STUB_VISIBILITY ; STUB_GH_FAIL=1 simule gh absent.
[[ "${STUB_GH_FAIL:-}" == "1" ]] && exit 1
printf '%s\n' "${STUB_VISIBILITY:-PUBLIC}"
GH
cat > "$work/bin/gstack-stub" <<'STUB'
#!/usr/bin/env bash
# Faux gstack-redact : une ligne contenant STUB_HIGH / STUB_MEDIUM devient une
# alerte ; codes 3 / 2 / 0 comme l'original ; STUB_EXIT force un autre code.
[[ -n "${STUB_CALLED:-}" ]] && : >> "$STUB_CALLED"
input="$(cat)"
python3 - "$input" <<'PY'
import json, sys
findings = []
for n, line in enumerate(sys.argv[1].split("\n"), 1):
    if "STUB_HIGH" in line:
        findings.append({"severity": "HIGH", "id": "stub.high", "line": n, "col": 1, "description": "faux identifiant", "preview": "ST********"})
    if "STUB_MEDIUM" in line:
        findings.append({"severity": "MEDIUM", "id": "stub.medium", "line": n, "col": 1, "description": "fausse PII", "preview": "ST********"})
print(json.dumps({"findings": findings}))
PY
[[ -n "${STUB_EXIT:-}" ]] && exit "$STUB_EXIT"
if grep -q STUB_HIGH <<< "$input"; then exit 3; fi
if grep -q STUB_MEDIUM <<< "$input"; then exit 2; fi
exit 0
STUB
chmod +x "$work/bin/gh" "$work/bin/gstack-stub"

# --- Un dépôt avec un distant déjà poussé ------------------------------------
export HOME="$work/home"; mkdir -p "$HOME"
export GSTACK_HOME="$work/gstack-home"
export PATH="$work/bin:$PATH"
export PULSE_GSTACK_REDACT="$work/bin/gstack-stub"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.invalid GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.invalid
git init -q --bare "$work/remote.git"
git init -q -b main "$work/repo"
cd "$work/repo"
git config core.hooksPath "$work/no-hooks"   # aucun hook réel pendant les tests
git remote add origin "$work/remote.git"
printf 'propre\n' > base.txt && git add base.txt && git commit -q -m "base"
git push -q origin main
base_sha="$(git rev-parse HEAD)"

out="$work/out.txt"
run_hook() { # $1 sha local ; stdin construit comme git le fait ; rend le code, sortie dans $out
  printf 'refs/heads/main %s refs/heads/main %s\n' "$1" "$base_sha" \
    | bash "$hook" origin "$work/remote.git" > "$out" 2>&1
  echo $?
}
new_commit() { # $1 fichier, $2 contenu, $3 message
  git checkout -q "$base_sha" 2>/dev/null
  printf '%s\n' "$2" > "$1" && git add "$1" && git commit -q -m "$3"
  git rev-parse HEAD
}
check() { # $1 nom, $2 attendu, $3 obtenu
  if [[ "$2" == "$3" ]]; then printf 'ok    %s\n' "$1"; else printf 'ÉCHEC %s : attendu %s, obtenu %s\n' "$1" "$2" "$3"; failures=$((failures + 1)); fi
}

# 1. Propre → 0
sha="$(new_commit a.txt "rien à signaler" "docs: rien")"
check "propre passe" 0 "$(run_hook "$sha")"

# 2. HIGH bloque → 1
sha="$(new_commit a.txt "clé STUB_HIGH ici" "feat: a")"
check "HIGH bloque (exit 1)" 1 "$(run_hook "$sha")"
check "HIGH : fichier et ligne listés" 1 "$(grep -c 'a.txt *1 *HIGH *stub.high' "$out")"

# 3. MEDIUM bloque → 2, liste brute
sha="$(new_commit b.txt "ligne 1
ligne STUB_MEDIUM en 2" "feat: b")"
check "MEDIUM bloque (exit 2)" 2 "$(run_hook "$sha")"
check "MEDIUM : fichier, ligne, détecteur, raison" 1 "$(grep -c 'b.txt *2 *MEDIUM *stub.medium *fausse PII' "$out")"
check "MEDIUM : aucun acquittement écrit" 0 "$(cat "$GSTACK_HOME/security/prepush-ack.jsonl" 2>/dev/null | wc -l | tr -d ' ')"

# 4. MEDIUM avec ACK → 0 et une ligne de journal
check "MEDIUM + PULSE_PREPUSH_ACK=1 passe" 0 "$(PULSE_PREPUSH_ACK=1 run_hook "$sha")"
check "ACK journalisé (une ligne)" 1 "$(wc -l < "$GSTACK_HOME/security/prepush-ack.jsonl" | tr -d ' ')"
check "ACK : détecteur consigné" 1 "$(grep -c '"stub.medium"' "$GSTACK_HOME/security/prepush-ack.jsonl")"

# 5. Dépôt privé → 0 sans appeler le scanner
sha="$(new_commit c.txt "STUB_HIGH" "feat: c")"
export STUB_CALLED="$work/called"; : > "$STUB_CALLED"
check "dépôt privé passe" 0 "$(STUB_VISIBILITY=PRIVATE run_hook "$sha")"
check "dépôt privé : scanner jamais appelé" 0 "$(wc -c < "$STUB_CALLED" | tr -d ' ')"
unset STUB_CALLED

# 6. gh en échec → supposé public → HIGH bloque
check "gh indisponible : supposé public" 1 "$(STUB_GH_FAIL=1 run_hook "$sha")"

# 7. Message de commit avec MEDIUM bloque, lignes propres
sha="$(new_commit d.txt "propre" "feat: d

Voir STUB_MEDIUM dans le corps")"
check "message de commit MEDIUM bloque (exit 2)" 2 "$(run_hook "$sha")"
check "message : commit et ligne listés" 1 "$(grep -c "commit $(git rev-parse --short "$sha") *3 *MEDIUM *stub.medium" "$out")"

# 8. Code de sortie inattendu de gstack propagé
sha="$(new_commit e.txt "propre" "feat: e")"
check "code de gstack propagé (7)" 7 "$(STUB_EXIT=7 run_hook "$sha")"

# 9. Suppression de branche : rien à scanner
printf 'refs/heads/x %s refs/heads/x %s\n' 0000000000000000000000000000000000000000 "$base_sha" | bash "$hook" origin > "$out" 2>&1
check "suppression de branche passe" 0 "$?"

if (( failures > 0 )); then echo "$failures échec(s)"; exit 1; fi
echo "tous les tests du hook passent"
