#!/bin/zsh
set -eu

PAGES_REPO_DIR="${PAGES_REPO_DIR:-/Users/wisdom/Projects/news/pages-repo}"
REMOTE_URL="${GITHUB_PAGES_REMOTE:-https://github.com/wisdom-crpto/daily-intelligence.git}"
BRANCH="${GITHUB_PAGES_BRANCH:-main}"

if [ ! -d "$PAGES_REPO_DIR/.git" ]; then
  echo "Pages repository is missing: $PAGES_REPO_DIR" >&2
  exit 1
fi

cd "$PAGES_REPO_DIR"

if [ -n "$(git status --porcelain)" ]; then
  echo "Refusing to publish a dirty worktree." >&2
  git status --short >&2
  exit 1
fi

git remote set-url origin "$REMOTE_URL"
git fetch origin "$BRANCH" --prune

read behind ahead <<EOF
$(git rev-list --left-right --count "origin/$BRANCH...HEAD")
EOF

if [ "$behind" -gt 0 ] && [ "$ahead" -gt 0 ]; then
  echo "Local and remote $BRANCH have diverged; manual review is required." >&2
  exit 1
fi

if [ "$behind" -gt 0 ]; then
  git merge --ff-only "origin/$BRANCH"
fi

if [ "$ahead" -gt 0 ]; then
  git push origin "HEAD:$BRANCH"
  echo "Published $ahead local commit(s) to origin/$BRANCH."
else
  echo "Nothing to publish; local and remote $BRANCH are current."
fi
