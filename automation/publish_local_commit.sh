#!/bin/zsh
set -eu

PAGES_REPO_DIR="${PAGES_REPO_DIR:-/Users/wisdom/Projects/news/pages-repo}"
REMOTE_URL="${GITHUB_PAGES_REMOTE:-https://github.com/wisdom-crpto/daily-intelligence.git}"
BRANCH="${GITHUB_PAGES_BRANCH:-main}"
GIT_BIN="${GIT_BIN:-git}"
PUBLISH_NETWORK_ATTEMPTS="${PUBLISH_NETWORK_ATTEMPTS:-3}"
PUBLISH_RETRY_BASE_SECONDS="${PUBLISH_RETRY_BASE_SECONDS:-20}"
SHLOCK_BIN="${SHLOCK_BIN:-/usr/bin/shlock}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"
}

case "$PUBLISH_NETWORK_ATTEMPTS" in
  ''|*[!0-9]*)
    echo "PUBLISH_NETWORK_ATTEMPTS must be an integer from 1 to 5." >&2
    exit 2
    ;;
esac
if [ "$PUBLISH_NETWORK_ATTEMPTS" -lt 1 ] || [ "$PUBLISH_NETWORK_ATTEMPTS" -gt 5 ]; then
  echo "PUBLISH_NETWORK_ATTEMPTS must be an integer from 1 to 5." >&2
  exit 2
fi

case "$PUBLISH_RETRY_BASE_SECONDS" in
  ''|*[!0-9]*)
    echo "PUBLISH_RETRY_BASE_SECONDS must be an integer from 0 to 300." >&2
    exit 2
    ;;
esac
if [ "$PUBLISH_RETRY_BASE_SECONDS" -gt 300 ]; then
  echo "PUBLISH_RETRY_BASE_SECONDS must be an integer from 0 to 300." >&2
  exit 2
fi

if [ ! -d "$PAGES_REPO_DIR/.git" ]; then
  echo "Pages repository is missing: $PAGES_REPO_DIR" >&2
  exit 1
fi

cd "$PAGES_REPO_DIR"

if [ ! -x "$SHLOCK_BIN" ]; then
  echo "Publisher lock helper is missing: $SHLOCK_BIN" >&2
  exit 2
fi

LOCK_FILE="$PAGES_REPO_DIR/.git/daily-intelligence-publish.lock"
if ! "$SHLOCK_BIN" -f "$LOCK_FILE" -p $$; then
  log "Another publisher process is already active; this invocation is skipped."
  exit 0
fi
trap 'rm -f -- "$LOCK_FILE"' EXIT

current_branch="$($GIT_BIN symbolic-ref --quiet --short HEAD)" || {
  echo "Publisher requires a named branch; detached HEAD is not allowed." >&2
  exit 2
}
if [ "$current_branch" != "$BRANCH" ]; then
  echo "Publisher requires branch $BRANCH; current branch is $current_branch." >&2
  exit 2
fi

if [ -n "$($GIT_BIN status --porcelain)" ]; then
  echo "Refusing to publish a dirty worktree." >&2
  $GIT_BIN status --short >&2
  exit 1
fi

if [ "$($GIT_BIN remote get-url origin)" != "$REMOTE_URL" ]; then
  $GIT_BIN remote set-url origin "$REMOTE_URL"
fi

# Most scheduled invocations have nothing to do. Avoid waking the network in
# that case, while still requiring a fresh fetch before every actual push.
if $GIT_BIN show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
  known_ahead="$($GIT_BIN rev-list --count "origin/$BRANCH..HEAD")"
  if [ "$known_ahead" -eq 0 ]; then
    log "Nothing to publish; no local commit is ahead of known origin/$BRANCH."
    exit 0
  fi
fi

publish_once() {
  $GIT_BIN fetch origin "$BRANCH" --prune || return $?

  local behind ahead
  read behind ahead <<EOF
$($GIT_BIN rev-list --left-right --count "origin/$BRANCH...HEAD")
EOF

  if [ "$behind" -gt 0 ] && [ "$ahead" -gt 0 ]; then
    echo "Local and remote $BRANCH have diverged; manual review is required." >&2
    return 3
  fi

  if [ "$behind" -gt 0 ]; then
    $GIT_BIN merge --ff-only "origin/$BRANCH" || return $?
  fi

  if [ "$ahead" -gt 0 ]; then
    $GIT_BIN merge-base --is-ancestor "origin/$BRANCH" HEAD || {
      echo "Remote ancestry check failed; refusing to push." >&2
      return 3
    }
    $GIT_BIN push origin "HEAD:$BRANCH" || return $?
    echo "Published $ahead local commit(s) to origin/$BRANCH."
  else
    echo "Nothing to publish; local and remote $BRANCH are current."
  fi
}

is_transient_network_error() {
  print -r -- "$1" | grep -Eiq \
    'could not resolve host|ssl[_ ](connect|connection)|connection (reset|timed out)|recv failure|failed to connect|network is unreachable|operation timed out|http (429|5[0-9][0-9])'
}

attempt=1
while [ "$attempt" -le "$PUBLISH_NETWORK_ATTEMPTS" ]; do
  log "Publication attempt $attempt/$PUBLISH_NETWORK_ATTEMPTS."
  if output="$(publish_once 2>&1)"; then
    [ -n "$output" ] && print -r -- "$output"
    log "Publication completed successfully."
    exit 0
  else
    exit_code=$?
  fi

  [ -n "$output" ] && print -r -- "$output" >&2

  if ! is_transient_network_error "$output"; then
    log "Publication stopped on a non-retryable safety or configuration error." >&2
    exit "$exit_code"
  fi

  if [ "$attempt" -ge "$PUBLISH_NETWORK_ATTEMPTS" ]; then
    log "Publication exhausted transient-network retries." >&2
    exit 75
  fi

  delay=$((PUBLISH_RETRY_BASE_SECONDS * attempt))
  log "Transient network failure; retrying in ${delay}s." >&2
  sleep "$delay"
  attempt=$((attempt + 1))
done
