#!/usr/bin/env bash
# Auto-sync for macOS/Linux: pull, scan for secrets, commit, push.
set -euo pipefail
cd "$(dirname "$0")"
branch=main
pattern='AIza[0-9A-Za-z_-]{30,}|gsk_[0-9A-Za-z]{20,}|sk-[A-Za-z0-9_-]{20,}|ghp_[0-9A-Za-z]{30,}|github_pat_[0-9A-Za-z_]{20,}|[MN][A-Za-z0-9]{23}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY'

git pull --rebase --autostash origin "$branch"
git add -A
if git diff --cached -U0 | grep -Eq "$pattern"; then
  git reset >/dev/null
  echo "Possible secret found. Nothing committed. Move it to the local config file." >&2
  exit 2
fi
if ! git diff --cached --quiet; then
  git commit -m "auto-sync $(date '+%Y-%m-%d %H:%M')"
  git push origin "$branch"
else
  echo "Nothing to commit."
fi
