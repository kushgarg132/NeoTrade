#!/bin/bash
# Install the plugins declared in .claude/settings.json. Cloud sessions have no
# one to answer the trust prompt that installs them on a local checkout, so the
# declarations are otherwise ignored. Reads the settings file so the list lives
# in one place. Idempotent; a failed install is logged and never blocks startup.
set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

settings="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/settings.json"
[ -f "$settings" ] || exit 0

known=$(claude plugin marketplace list 2>/dev/null || true)
installed=$(claude plugin list 2>/dev/null || true)

jq -r '.extraKnownMarketplaces // {} | to_entries[]
       | select(.value.source.source == "github") | "\(.key) \(.value.source.repo)"' "$settings" |
while read -r name repo; do
  grep -qw -- "$name" <<<"$known" && continue
  claude plugin marketplace add "$repo" >/dev/null 2>&1 ||
    echo "session-start: could not add marketplace $repo" >&2
done

jq -r '.enabledPlugins // {} | to_entries[] | select(.value == true) | .key' "$settings" |
while read -r plugin; do
  grep -qF -- "$plugin" <<<"$installed" && continue
  claude plugin install "$plugin" >/dev/null 2>&1 ||
    echo "session-start: could not install $plugin" >&2
done

exit 0
