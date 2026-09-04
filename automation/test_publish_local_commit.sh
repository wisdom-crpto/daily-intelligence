#!/bin/zsh
set -eu

SCRIPT_DIR="${0:A:h}"
PUBLISHER="$SCRIPT_DIR/publish_local_commit.sh"
TEST_ROOT="$(mktemp -d /private/tmp/daily-intelligence-publisher-test.XXXXXX)"
trap 'rm -rf "$TEST_ROOT"' EXIT

REAL_GIT="$(command -v git)"
REMOTE="$TEST_ROOT/remote.git"
SEED="$TEST_ROOT/seed"
LOCAL="$TEST_ROOT/local"
OTHER="$TEST_ROOT/other"
FAKE_GIT="$TEST_ROOT/fake-git"
COUNTER="$TEST_ROOT/fetch-count"

git init --bare -q "$REMOTE"
git init -q -b main "$SEED"
git -C "$SEED" config user.name test
git -C "$SEED" config user.email test@example.invalid
print 'initial' > "$SEED/issue.txt"
git -C "$SEED" add issue.txt
git -C "$SEED" commit -q -m initial
git -C "$SEED" remote add origin "$REMOTE"
git -C "$SEED" push -q -u origin main
git --git-dir="$REMOTE" symbolic-ref HEAD refs/heads/main
git clone -q "$REMOTE" "$LOCAL"
git -C "$LOCAL" config user.name test
git -C "$LOCAL" config user.email test@example.invalid

cat > "$FAKE_GIT" <<'EOF'
#!/bin/zsh
set -eu
if [ "${1:-}" = "fetch" ]; then
  count=0
  [ ! -f "$PUBLISH_TEST_COUNTER" ] || read count < "$PUBLISH_TEST_COUNTER"
  count=$((count + 1))
  print "$count" > "$PUBLISH_TEST_COUNTER"
  if [ "${PUBLISH_TEST_MODE:-}" = "transient" ] && [ "$count" -le "${PUBLISH_TEST_FAILS:-0}" ]; then
    echo "fatal: unable to access remote: LibreSSL SSL_connect: SSL_ERROR_SYSCALL" >&2
    exit 128
  fi
  if [ "${PUBLISH_TEST_MODE:-}" = "permanent" ]; then
    echo "fatal: Authentication failed" >&2
    exit 128
  fi
  if [ "${PUBLISH_TEST_MODE:-}" = "forbid-fetch" ]; then
    echo "unexpected fetch" >&2
    exit 97
  fi
fi
exec "$PUBLISH_TEST_REAL_GIT" "$@"
EOF
chmod +x "$FAKE_GIT"

print 'daily one' >> "$LOCAL/issue.txt"
git -C "$LOCAL" add issue.txt
git -C "$LOCAL" commit -q -m 'daily one'

PAGES_REPO_DIR="$LOCAL" \
GITHUB_PAGES_REMOTE="$REMOTE" \
GIT_BIN="$FAKE_GIT" \
PUBLISH_NETWORK_ATTEMPTS=3 \
PUBLISH_RETRY_BASE_SECONDS=0 \
PUBLISH_TEST_REAL_GIT="$REAL_GIT" \
PUBLISH_TEST_COUNTER="$COUNTER" \
PUBLISH_TEST_MODE=transient \
PUBLISH_TEST_FAILS=2 \
  "$PUBLISHER" > "$TEST_ROOT/transient.out" 2>&1 || {
    sed -n '1,200p' "$TEST_ROOT/transient.out" >&2
    exit 1
  }

read fetch_count < "$COUNTER"
[ "$fetch_count" = "3" ]
[ "$(git -C "$LOCAL" rev-parse HEAD)" = "$(git --git-dir="$REMOTE" rev-parse main)" ]
grep -q 'Publication completed successfully' "$TEST_ROOT/transient.out"

# With no pending local commit, the publisher must not make a network call.
rm -f "$COUNTER"
PAGES_REPO_DIR="$LOCAL" \
GITHUB_PAGES_REMOTE="$REMOTE" \
GIT_BIN="$FAKE_GIT" \
PUBLISH_TEST_REAL_GIT="$REAL_GIT" \
PUBLISH_TEST_COUNTER="$COUNTER" \
PUBLISH_TEST_MODE=forbid-fetch \
  "$PUBLISHER" > "$TEST_ROOT/noop.out" 2>&1
[ ! -e "$COUNTER" ]
grep -q 'no local commit is ahead' "$TEST_ROOT/noop.out"

# Authentication and permission failures are not transient and must not retry.
print 'daily two' >> "$LOCAL/issue.txt"
git -C "$LOCAL" add issue.txt
git -C "$LOCAL" commit -q -m 'daily two'
rm -f "$COUNTER"
if PAGES_REPO_DIR="$LOCAL" \
  GITHUB_PAGES_REMOTE="$REMOTE" \
  GIT_BIN="$FAKE_GIT" \
  PUBLISH_NETWORK_ATTEMPTS=3 \
  PUBLISH_RETRY_BASE_SECONDS=0 \
  PUBLISH_TEST_REAL_GIT="$REAL_GIT" \
  PUBLISH_TEST_COUNTER="$COUNTER" \
  PUBLISH_TEST_MODE=permanent \
    "$PUBLISHER" > "$TEST_ROOT/permanent.out" 2>&1; then
  echo 'Expected permanent authentication failure.' >&2
  exit 1
fi
read fetch_count < "$COUNTER"
[ "$fetch_count" = "1" ]
grep -q 'non-retryable safety or configuration error' "$TEST_ROOT/permanent.out"

# Transient failures stop after the configured bound and use a retryable exit.
rm -f "$COUNTER"
set +e
PAGES_REPO_DIR="$LOCAL" \
GITHUB_PAGES_REMOTE="$REMOTE" \
GIT_BIN="$FAKE_GIT" \
PUBLISH_NETWORK_ATTEMPTS=3 \
PUBLISH_RETRY_BASE_SECONDS=0 \
PUBLISH_TEST_REAL_GIT="$REAL_GIT" \
PUBLISH_TEST_COUNTER="$COUNTER" \
PUBLISH_TEST_MODE=transient \
PUBLISH_TEST_FAILS=9 \
  "$PUBLISHER" > "$TEST_ROOT/exhausted.out" 2>&1
exhausted_status=$?
set -e
[ "$exhausted_status" = "75" ]
read fetch_count < "$COUNTER"
[ "$fetch_count" = "3" ]
grep -q 'exhausted transient-network retries' "$TEST_ROOT/exhausted.out"

# Wrong-branch, dirty-worktree, and concurrent invocations fail or skip safely
# before making a network call.
git -C "$LOCAL" switch -q -c not-main
if PAGES_REPO_DIR="$LOCAL" GITHUB_PAGES_REMOTE="$REMOTE" \
    "$PUBLISHER" > "$TEST_ROOT/branch.out" 2>&1; then
  echo 'Expected wrong-branch safety stop.' >&2
  exit 1
fi
grep -q 'requires branch main' "$TEST_ROOT/branch.out"
git -C "$LOCAL" switch -q main

print 'dirty' > "$LOCAL/untracked.txt"
if PAGES_REPO_DIR="$LOCAL" GITHUB_PAGES_REMOTE="$REMOTE" \
    "$PUBLISHER" > "$TEST_ROOT/dirty.out" 2>&1; then
  echo 'Expected dirty-worktree safety stop.' >&2
  exit 1
fi
grep -q 'dirty worktree' "$TEST_ROOT/dirty.out"
rm -f "$LOCAL/untracked.txt"

LOCK_FILE="$LOCAL/.git/daily-intelligence-publish.lock"
/usr/bin/shlock -f "$LOCK_FILE" -p $$
PAGES_REPO_DIR="$LOCAL" GITHUB_PAGES_REMOTE="$REMOTE" \
  "$PUBLISHER" > "$TEST_ROOT/lock.out" 2>&1
grep -q 'already active' "$TEST_ROOT/lock.out"
rm -f "$LOCK_FILE"

# Divergence is a safety stop, never an automatic merge or retry.
git clone -q "$REMOTE" "$OTHER"
git -C "$OTHER" config user.name test
git -C "$OTHER" config user.email test@example.invalid
print 'remote change' >> "$OTHER/issue.txt"
git -C "$OTHER" add issue.txt
git -C "$OTHER" commit -q -m 'remote change'
git -C "$OTHER" push -q origin main
if PAGES_REPO_DIR="$LOCAL" \
  GITHUB_PAGES_REMOTE="$REMOTE" \
  PUBLISH_NETWORK_ATTEMPTS=3 \
  PUBLISH_RETRY_BASE_SECONDS=0 \
    "$PUBLISHER" > "$TEST_ROOT/diverged.out" 2>&1; then
  echo 'Expected divergence safety stop.' >&2
  exit 1
fi
grep -q 'have diverged' "$TEST_ROOT/diverged.out"

echo 'Publisher tests passed: retry bounds, no-op, auth, branch, dirty, lock, and divergence safety.'
