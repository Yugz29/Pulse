#!/usr/bin/env bash
# prepush_local.sh — second étage du hook de pré-poussée de Pulse (dépôt public),
# installé par `make hooks` comme hook local de gstack (copie hors dépôt, sous
# le nom que le wrapper gstack de `.git/hooks/pre-push` chaîne AVANT
# `gstack-redact-prepush`, avec le même stdin ; il s'arrête sur un code non
# nul). Ne touche ni au wrapper gstack ni à core.hooksPath.
#
# Ce que gstack ne fait pas et que cet étage fait :
#   - visibilité lue par `gh repo view` (échec → supposée publique) ;
#   - scan en mode public des lignes ajoutées ET des messages de commit ;
#   - MEDIUM : liste brute (fichier ou commit, ligne, détecteur, raison,
#     aperçu masqué par gstack) puis exit 2, sauf PULSE_PREPUSH_ACK=1 :
#     poussée autorisée et une ligne dans ~/.gstack/security/prepush-ack.jsonl ;
#   - HIGH : même liste, exit 1 ;
#   - tout autre code de gstack-redact (usage, crash) est propagé tel quel.
# Aucune lecture sur /dev/tty. Rien n'est écrit dans le dépôt.
#
# Variables : PULSE_GSTACK_REDACT (commande du scanner, défaut : bun sur le
# gstack-redact de ~/.claude/skills/gstack), GSTACK_HOME (défaut ~/.gstack),
# PULSE_PREPUSH_ACK=1 (accord explicite de l'utilisateur, pour une poussée).
set -u

remote_name="${1:-origin}"
remote_url="${2:-}"
scanner="${PULSE_GSTACK_REDACT:-bun $HOME/.claude/skills/gstack/bin/gstack-redact}"
gstack_home="${GSTACK_HOME:-$HOME/.gstack}"
ZERO='^0+$'

log() { printf 'hook local gstack: %s\n' "$*" >&2; }

# --- Visibilité ---------------------------------------------------------------
visibility=""
if [[ -n "$remote_url" ]]; then
  visibility="$(gh repo view "$remote_url" --json visibility -q .visibility 2>/dev/null || true)"
fi
if [[ -z "$visibility" ]]; then
  visibility="$(gh repo view --json visibility -q .visibility 2>/dev/null || true)"
fi
visibility="$(printf '%s' "$visibility" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
case "$visibility" in
  private|internal) log "dépôt $visibility : pas de scan public." ; exit 0 ;;
  public) ;;
  *) log "visibilité inconnue (gh indisponible ou muet) : supposée publique." ;;
esac

# --- Plages poussées ----------------------------------------------------------
default_branch() {
  local sym
  sym="$(git symbolic-ref -q "refs/remotes/$remote_name/HEAD" 2>/dev/null || true)"
  if [[ -n "$sym" ]]; then printf '%s' "${sym#refs/remotes/}"; return; fi
  for b in "$remote_name/main" "$remote_name/master"; do
    if git rev-parse -q --verify "$b" >/dev/null 2>&1; then printf '%s' "$b"; return; fi
  done
  printf '%s' "$remote_name/main"
}

tmp="$(mktemp -d "${TMPDIR:-/tmp}/pulse-prepush.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
lines_text="$tmp/lines.txt"; lines_map="$tmp/lines.map"
msgs_text="$tmp/msgs.txt";   msgs_map="$tmp/msgs.map"
: > "$lines_text"; : > "$lines_map"; : > "$msgs_text"; : > "$msgs_map"
ranges=()

while read -r _local_ref local_sha _remote_ref remote_sha; do
  [[ -z "${local_sha:-}" ]] && continue
  [[ "$local_sha" =~ $ZERO ]] && continue          # suppression de branche
  if [[ -z "${remote_sha:-}" || "$remote_sha" =~ $ZERO ]] \
     || ! git cat-file -e "$remote_sha" 2>/dev/null; then
    base="$(git merge-base "$local_sha" "$(default_branch)" 2>/dev/null || true)"
    if [[ -n "$base" ]]; then range="$base..$local_sha"; else range="$local_sha"; fi
  else
    range="$remote_sha..$local_sha"
  fi
  ranges+=("$range")

  # Lignes ajoutées, avec leur fichier et leur numéro dans la nouvelle version.
  if [[ "$range" == *..* ]]; then diff_range="$range"; else diff_range="4b825dc642cb6eb9a060e54bf8d69288fbee4904..$local_sha"; fi
  git diff --unified=0 --no-color --no-ext-diff --no-textconv "$diff_range" \
    | awk -v text="$lines_text" -v map="$lines_map" '
        /^diff --git / { file=""; inhunk=0; next }
        /^\+\+\+ / { if (!inhunk) { file=$2; sub(/^b\//, "", file) } ; next }
        /^--- / { if (!inhunk) next }
        /^@@ / { inhunk=1; split($3, a, ","); sub(/^\+/, "", a[1]); n=a[1]+0; next }
        inhunk && /^\+/ { print substr($0, 2) >> text; print file "\t" n >> map; n++; next }
        inhunk && /^ / { n++ }
      '

  # Messages de commit, un bloc par commit, avec le numéro de ligne dans le message.
  for sha in $(git rev-list --reverse "$range" 2>/dev/null); do
    short="$(git rev-parse --short "$sha")"
    git log -1 --format=%B "$sha" | awk -v text="$msgs_text" -v map="$msgs_map" -v c="commit $short" '
      { print $0 >> text; print c "\t" NR >> map }'
  done
done

# --- Scan ---------------------------------------------------------------------
scan() { # $1 texte, $2 carte, $3 sortie json ; rend le code de gstack-redact
  [[ -s "$1" ]] || { printf '{"findings":[]}' > "$3"; return 0; }
  $scanner --repo-visibility public --json < "$1" > "$3"
}

findings="$tmp/findings.tsv"; : > "$findings"
for kind in lines msgs; do
  if [[ "$kind" == lines ]]; then text="$lines_text"; map="$lines_map"; else text="$msgs_text"; map="$msgs_map"; fi
  scan "$text" "$map" "$tmp/$kind.json"; rc=$?
  case "$rc" in 0|2|3) ;; *) log "gstack-redact a rendu $rc sur les $kind : poussée refusée (code propagé)."; exit "$rc" ;; esac
  python3 - "$map" "$tmp/$kind.json" >> "$findings" <<'PY'
import json, sys
places = [l.rstrip("\n").split("\t") for l in open(sys.argv[1], encoding="utf-8", errors="replace")]
try:
    data = json.load(open(sys.argv[2]))
except Exception as exc:
    print(f"?\t?\tHIGH\tengine.unreadable\tsortie JSON de gstack-redact illisible ({exc})\t")
    sys.exit(0)
for f in data.get("findings", []):
    sev = f.get("severity")
    if sev not in ("HIGH", "MEDIUM"):
        continue
    i = int(f.get("line", 0)) - 1
    where, num = (places[i] if 0 <= i < len(places) else ("?", "?"))
    print("\t".join([where, str(num), sev, str(f.get("id", "")), str(f.get("description", "")), str(f.get("preview", ""))]))
PY
done

high="$(awk -F'\t' '$3=="HIGH"' "$findings" | wc -l | tr -d ' ')"
medium="$(awk -F'\t' '$3=="MEDIUM"' "$findings" | wc -l | tr -d ' ')"

if (( high == 0 && medium == 0 )); then
  exit 0
fi

{
  printf '\nhook local gstack — dépôt public, %s HIGH, %s MEDIUM sur %s (lignes ajoutées + messages) :\n' "$high" "$medium" "${ranges[*]}"
  printf '  %-44s %-6s %-7s %-24s %s\n' "où" "ligne" "niveau" "détecteur" "raison · aperçu"
  awk -F'\t' '{ printf "  %-44s %-6s %-7s %-24s %s · %s\n", $1, $2, $3, $4, $5, $6 }' "$findings"
  printf '\n'
} >&2

if (( high > 0 )); then
  log "HIGH : poussée refusée. Retirer ou faire tourner l'identifiant, puis repousser."
  exit 1
fi

if [[ "${PULSE_PREPUSH_ACK:-}" == "1" ]]; then
  mkdir -p "$gstack_home/security" 2>/dev/null
  python3 - "$gstack_home/security/prepush-ack.jsonl" "$remote_name" "${ranges[*]}" "$medium" "$findings" <<'PY'
import json, sys, datetime
path, remote, ranges, medium, findings = sys.argv[1:6]
ids = sorted({l.split("\t")[3] for l in open(findings, encoding="utf-8", errors="replace") if l.strip()})
line = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(), "remote": remote,
        "ranges": ranges, "medium": int(medium), "detectors": ids, "ack": "PULSE_PREPUSH_ACK=1"}
with open(path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(line, ensure_ascii=False) + "\n")
PY
  log "MEDIUM acquitté par PULSE_PREPUSH_ACK=1 : poussée autorisée, consignée dans $gstack_home/security/prepush-ack.jsonl."
  exit 0
fi

log "MEDIUM : poussée refusée (exit 2). Lire la liste ; si l'utilisateur la classe fausse : PULSE_PREPUSH_ACK=1 git push …"
exit 2
