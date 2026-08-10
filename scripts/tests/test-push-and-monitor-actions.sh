#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
script="$repo_root/scripts/push-and-monitor-actions.sh"
test_dir="$(mktemp -d)"
fake_bin="$test_dir/bin"
mkdir -p "$fake_bin"
trap 'rm -rf "$test_dir"' EXIT

full_sha="86ee52c98b7151dd12591c1a8e39808201270691"

cat >"$fake_bin/git" <<EOF
#!/usr/bin/env bash
case "\${1:-} \${2:-}" in
  "rev-parse --show-toplevel") printf '%s\\n' '$repo_root' ;;
  "rev-parse --verify") printf '%s\\n' '$full_sha' ;;
  "push ") printf 'push\\n' >>"\$FAKE_GIT_LOG" ;;
  push*) printf 'push\\n' >>"\$FAKE_GIT_LOG" ;;
  *) printf 'unexpected fake git args: %s\\n' "\$*" >&2; exit 90 ;;
esac
EOF

cat >"$fake_bin/gh" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-} ${2:-}" == "auth status" ]]; then
  [[ "${SCENARIO:-}" != "auth-failure" ]]
  exit
fi
if [[ "${1:-} ${2:-}" == "run list" ]]; then
  case "${SCENARIO:-}" in
    no-run) exit 0 ;;
    *) printf '12345\tqueued\t-\thttps://example.test/run/12345\n' ;;
  esac
  exit
fi
if [[ "${1:-} ${2:-}" == "run view" ]]; then
  case "${SCENARIO:-}" in
    success) printf 'completed\tsuccess\thttps://example.test/run/12345\n' ;;
    failure) printf 'completed\tfailure\thttps://example.test/run/12345\n' ;;
    *) printf 'unexpected scenario: %s\n' "${SCENARIO:-}" >&2; exit 91 ;;
  esac
  exit
fi
printf 'unexpected fake gh args: %s\n' "$*" >&2
exit 92
EOF

chmod +x "$fake_bin/git" "$fake_bin/gh"

"$script" --help | grep -q -- '--delay SECONDS    Wait before looking for the run (default: 60).'

run_case() {
  local scenario="$1"
  local expected_status="$2"
  shift 2
  local output_file="$test_dir/$scenario.out"
  local git_log="$test_dir/$scenario.git.log"
  : >"$git_log"

  set +e
  PATH="$fake_bin:$PATH" \
    SCENARIO="$scenario" \
    FAKE_GIT_LOG="$git_log" \
    "$script" "$@" >"$output_file" 2>&1
  local actual_status=$?
  set -e

  if [[ "$actual_status" != "$expected_status" ]]; then
    cat "$output_file" >&2
    printf '%s: expected status %s, got %s\n' \
      "$scenario" "$expected_status" "$actual_status" >&2
    exit 1
  fi
}

run_case success 0 --delay 0 --timeout 2 --poll 1
grep -q 'GitHub Actions succeeded' "$test_dir/success.out"
grep -q '^push$' "$test_dir/success.git.log"

run_case failure 1 --skip-push --delay 0 --timeout 2 --poll 1
grep -q 'finished with failure' "$test_dir/failure.out"
[[ ! -s "$test_dir/failure.git.log" ]]

run_case no-run 124 --skip-push --delay 0 --timeout 0 --poll 1
grep -q 'no push-triggered ci.yml run found' "$test_dir/no-run.out"

run_case auth-failure 2 --delay 0 --timeout 2 --poll 1
grep -q 'gh is not authenticated' "$test_dir/auth-failure.out"
[[ ! -s "$test_dir/auth-failure.git.log" ]]

printf 'push-and-monitor-actions tests: OK\n'
