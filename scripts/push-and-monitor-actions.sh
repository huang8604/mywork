#!/usr/bin/env bash

set -uo pipefail

workflow="ci.yml"
delay_seconds=60
timeout_seconds=1800
poll_seconds=10
skip_push=0
requested_sha=""
push_args=()

usage() {
  cat <<'EOF'
Usage:
  scripts/push-and-monitor-actions.sh [monitor options] [-- git-push-options]

Push HEAD, wait for its GitHub Actions run, and monitor it to completion.

Monitor options:
  --skip-push        Monitor an already-pushed commit without running git push.
  --sha SHA          Commit to monitor (default: HEAD).
  --workflow FILE    Workflow file/name passed to gh (default: ci.yml).
  --delay SECONDS    Wait before looking for the run (default: 60).
  --timeout SECONDS  Maximum discovery/monitoring time (default: 1800).
  --poll SECONDS     Poll interval after the initial delay (default: 10).
  -h, --help         Show this help.

Examples:
  scripts/push-and-monitor-actions.sh
  scripts/push-and-monitor-actions.sh -- --set-upstream origin main
  scripts/push-and-monitor-actions.sh --skip-push --sha 86ee52c --delay 0
EOF
}

die() {
  printf 'error: %s\n' "$1" >&2
  exit "${2:-2}"
}

require_value() {
  local option="$1"
  local value="${2:-}"
  [[ -n "$value" ]] || die "$option requires a value"
}

require_nonnegative_integer() {
  local option="$1"
  local value="$2"
  [[ "$value" =~ ^[0-9]+$ ]] || die "$option must be a non-negative integer"
}

while (($# > 0)); do
  case "$1" in
    --skip-push)
      skip_push=1
      shift
      ;;
    --sha)
      require_value "$1" "${2:-}"
      requested_sha="$2"
      shift 2
      ;;
    --workflow)
      require_value "$1" "${2:-}"
      workflow="$2"
      shift 2
      ;;
    --delay)
      require_value "$1" "${2:-}"
      delay_seconds="$2"
      shift 2
      ;;
    --timeout)
      require_value "$1" "${2:-}"
      timeout_seconds="$2"
      shift 2
      ;;
    --poll)
      require_value "$1" "${2:-}"
      poll_seconds="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      push_args=("$@")
      break
      ;;
    *)
      die "unknown option '$1' (put git push options after --)"
      ;;
  esac
done

require_nonnegative_integer "--delay" "$delay_seconds"
require_nonnegative_integer "--timeout" "$timeout_seconds"
require_nonnegative_integer "--poll" "$poll_seconds"
((poll_seconds > 0)) || die "--poll must be greater than zero"

command -v git >/dev/null 2>&1 || die "git is required"
command -v gh >/dev/null 2>&1 || die "GitHub CLI (gh) is required"
git rev-parse --show-toplevel >/dev/null 2>&1 || die "run this script inside a Git repository"
gh auth status --hostname github.com >/dev/null 2>&1 \
  || die "gh is not authenticated; run: gh auth login"

sha_source="${requested_sha:-HEAD}"
sha="$(git rev-parse --verify "${sha_source}^{commit}" 2>/dev/null)" \
  || die "cannot resolve commit '$sha_source'"

if ((skip_push == 0)); then
  printf 'Pushing commit %s...\n' "$sha"
  git push "${push_args[@]}" || die "git push failed" 1
else
  printf 'Skipping push; monitoring commit %s.\n' "$sha"
fi

if ((delay_seconds > 0)); then
  printf 'Waiting %ss for GitHub Actions to enqueue...\n' "$delay_seconds"
  sleep "$delay_seconds"
fi

deadline=$((SECONDS + timeout_seconds))
run_id=""
run_url=""
last_state=""
api_failures=0

while ((SECONDS <= deadline)); do
  if [[ -z "$run_id" ]]; then
    jq_filter="map(select(.headSha == \"$sha\" and .event == \"push\")) | first | if . == null then \"\" else [.databaseId, .status, (if .conclusion == \"\" then \"-\" else (.conclusion // \"-\") end), .url] | @tsv end"
    if ! run_data="$(gh run list \
      --workflow "$workflow" \
      --commit "$sha" \
      --limit 20 \
      --json databaseId,headSha,status,conclusion,event,url,createdAt \
      --jq "$jq_filter" 2>&1)"; then
      api_failures=$((api_failures + 1))
      printf 'GitHub API error while discovering the run (%d/3): %s\n' \
        "$api_failures" "$run_data" >&2
      if ((api_failures >= 3)); then
        die "failed to query GitHub Actions three times"
      fi
    elif [[ -n "$run_data" ]]; then
      api_failures=0
      IFS=$'\t' read -r run_id status conclusion run_url <<<"$run_data"
      printf 'Found run %s: %s\n' "$run_id" "$run_url"
    else
      api_failures=0
      status="waiting-for-run"
      conclusion="-"
    fi
  else
    jq_filter='[.status, (if .conclusion == "" then "-" else (.conclusion // "-") end), .url] | @tsv'
    if ! run_data="$(gh run view "$run_id" \
      --json status,conclusion,url \
      --jq "$jq_filter" 2>&1)"; then
      api_failures=$((api_failures + 1))
      printf 'GitHub API error while reading run %s (%d/3): %s\n' \
        "$run_id" "$api_failures" "$run_data" >&2
      if ((api_failures >= 3)); then
        die "failed to query GitHub Actions three times"
      fi
      status="api-retry"
      conclusion="-"
    else
      api_failures=0
      IFS=$'\t' read -r status conclusion run_url <<<"$run_data"
    fi
  fi

  state="${status:-unknown}/${conclusion:--}"
  if [[ "$state" != "$last_state" ]]; then
    printf 'Actions state: %s\n' "$state"
    last_state="$state"
  fi

  if [[ "${status:-}" == "completed" ]]; then
    if [[ "$conclusion" == "success" ]]; then
      printf 'GitHub Actions succeeded: %s\n' "$run_url"
      exit 0
    fi
    printf 'GitHub Actions finished with %s: %s\n' "$conclusion" "$run_url" >&2
    exit 1
  fi

  remaining=$((deadline - SECONDS))
  ((remaining > 0)) || break
  sleep_for="$poll_seconds"
  ((sleep_for <= remaining)) || sleep_for="$remaining"
  sleep "$sleep_for"
done

if [[ -n "$run_id" ]]; then
  printf 'Timed out after %ss while monitoring run %s: %s\n' \
    "$timeout_seconds" "$run_id" "$run_url" >&2
else
  printf 'Timed out after %ss: no push-triggered %s run found for %s.\n' \
    "$timeout_seconds" "$workflow" "$sha" >&2
  printf 'Check that the commit was pushed to main and GitHub Actions is enabled.\n' >&2
fi
exit 124
