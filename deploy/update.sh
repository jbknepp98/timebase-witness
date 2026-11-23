#!/usr/bin/env bash
# Update a Witness deployment from git.
#   deploy/update.sh            pull; rebuild + restart the gateway only if gateway/ changed
#   deploy/update.sh --rebuild  pull; always rebuild + restart the gateway
# The page is served straight from ../site, so a pull updates it in place. A gateway restart resets
# what Handoffs has observed, so it is skipped when gateway/ did not change.
#
# Host-specific settings (optional) go in deploy/update.local.env, which git ignores, e.g.
#   DOCKER=/path/to/docker
#   DOCKER_CONFIG=/path/to/a/docker-config-without-a-credential-store
set -euo pipefail
cd "$(dirname "$0")"
[[ -f update.local.env ]] && { set -a; source update.local.env; set +a; }
DOCKER=${DOCKER:-docker}

before=$(git rev-parse --short HEAD)
git pull --ff-only -q
after=$(git rev-parse --short HEAD)
echo "Witness: $before -> $after"

rebuild=no
[[ "${1:-}" == "--rebuild" ]] && rebuild=yes
"$DOCKER" image inspect witness-gateway:current >/dev/null 2>&1 || rebuild=yes
git diff --quiet "$before" "$after" -- ../gateway || rebuild=yes

if [[ $rebuild == yes ]]; then
  # keep the image being replaced, so the rollback below always has something to point at
  "$DOCKER" image inspect witness-gateway:current >/dev/null 2>&1 && "$DOCKER" tag witness-gateway:current witness-gateway:previous
  "$DOCKER" compose build -q gateway
  "$DOCKER" tag witness-gateway:current "witness-gateway:git-$after"
  echo "Gateway rebuilt (witness-gateway:git-$after); restarting. To roll back:"
  echo "  $DOCKER tag witness-gateway:previous witness-gateway:current && $DOCKER compose up -d --force-recreate gateway"
  "$DOCKER" compose up -d --force-recreate gateway
else
  echo "Gateway unchanged; page updated in place."
fi
"$DOCKER" compose up -d web >/dev/null
