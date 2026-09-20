#!/usr/bin/env bash
set -Eeuo pipefail

umask 027

repo_dir="${XUHUA_REPO_DIR:-/opt/xuhua/repo}"
env_file="${XUHUA_ENV_FILE:-/etc/xuhua/xuhua.env}"
lock_file="${XUHUA_LOCK_FILE:-/var/lib/xuhua/deploy.lock}"
failed_sha_file="${XUHUA_FAILED_SHA_FILE:-/var/lib/xuhua/failed-sha}"
last_good_compose="${XUHUA_LAST_GOOD_COMPOSE:-/var/lib/xuhua/last-good-compose.yaml}"
last_good_sha_file="${XUHUA_LAST_GOOD_SHA_FILE:-/var/lib/xuhua/last-good-sha}"
previous_good_sha_file="${XUHUA_PREVIOUS_GOOD_SHA_FILE:-/var/lib/xuhua/previous-good-sha}"
failure_cooldown="${XUHUA_FAILURE_COOLDOWN:-600}"
fetch_timeout="${XUHUA_FETCH_TIMEOUT:-180}"
compose_file="$repo_dir/compose.yaml"
expected_https_origin="https://github.com/RinoPaw/xuhua.git"
expected_ssh_origin="ssh://git@ssh.github.com:443/RinoPaw/xuhua.git"

export GIT_TERMINAL_PROMPT=0

if [[ ! "$failure_cooldown" =~ ^[0-9]+$ ]]; then
  failure_cooldown=600
fi

if [[ ! "$fetch_timeout" =~ ^[1-9][0-9]*$ ]]; then
  fetch_timeout=180
fi

exec 9>"$lock_file"
if ! flock -n 9; then
  exit 0
fi

if [[ ! -f "$env_file" ]]; then
  echo "Missing deployment environment file: $env_file" >&2
  exit 1
fi

cd "$repo_dir"

if [[ "$(git symbolic-ref --short HEAD)" != "main" ]]; then
  echo "Deployment checkout must stay on the main branch." >&2
  exit 1
fi

origin_url="$(git remote get-url origin)"
case "$origin_url" in
  "$expected_https_origin")
    fetch_command=(git -c http.version=HTTP/1.1 fetch -4 --prune origin main)
    ;;
  "$expected_ssh_origin")
    fetch_command=(git fetch --prune origin main)
    ;;
  *)
    echo "Unexpected Git origin; refusing to deploy." >&2
    exit 1
    ;;
esac

if [[ -n "$(git status --porcelain=v1 --untracked-files=all)" ]]; then
  echo "Deployment checkout is dirty; refusing to overwrite local changes." >&2
  exit 1
fi

if [[ -e .env || -e compose.override.yml || -e compose.override.yaml ]]; then
  echo "Repository-local deployment overrides are not permitted." >&2
  exit 1
fi

if ! timeout --foreground "${fetch_timeout}s" "${fetch_command[@]}"; then
  echo "GitHub fetch failed or exceeded ${fetch_timeout} seconds." >&2
  exit 1
fi
local_sha="$(git rev-parse HEAD)"
remote_sha="$(git rev-parse origin/main)"

if ! git merge-base --is-ancestor "$local_sha" "$remote_sha"; then
  echo "Local main is not an ancestor of origin/main; refusing to deploy local-only commits." >&2
  exit 1
fi

git merge --ff-only "$remote_sha"
commit_sha="$(git rev-parse HEAD)"

if [[ "$commit_sha" != "$remote_sha" ]]; then
  echo "Checkout does not exactly match origin/main." >&2
  exit 1
fi

previous_commit="$(docker inspect --format '{{ index .Config.Labels "io.xuhua.commit" }}' xuhua 2>/dev/null || true)"
previous_env_revision="$(docker inspect --format '{{ index .Config.Labels "io.xuhua.env-revision" }}' xuhua 2>/dev/null || true)"
container_running="$(docker inspect --format '{{ .State.Running }}' xuhua 2>/dev/null || true)"
container_health="$(docker inspect --format '{{ if .State.Health }}{{ .State.Health.Status }}{{ end }}' xuhua 2>/dev/null || true)"

env_revision="$(stat -c '%i:%s:%y:%z' "$env_file" | sha256sum | awk '{print $1}')"
recent_failure=0
failed_env_revision=""
if [[ -r "$failed_sha_file" ]] && read -r failed_sha failed_field failed_at <"$failed_sha_file"; then
  if [[ -z "${failed_at:-}" ]]; then
    failed_at="$failed_field"
  else
    failed_env_revision="$failed_field"
  fi
  now="$(date +%s)"
  if [[ "$failed_sha" == "$commit_sha" && "$failed_env_revision" == "$env_revision" && "$failed_at" =~ ^[0-9]+$ && $((now - failed_at)) -lt "$failure_cooldown" ]]; then
    recent_failure=1
  fi
fi

export XUHUA_COMMIT="$commit_sha"
export XUHUA_ENV_FILE="$env_file"
export XUHUA_ENV_REVISION="$env_revision"

compose_with() {
  local selected_compose="$1"
  shift
  env \
    -u COMPOSE_FILE \
    -u COMPOSE_PROJECT_NAME \
    -u COMPOSE_PROFILES \
    -u COMPOSE_ENV_FILES \
    -u DOCKER_CONTEXT \
    -u DOCKER_HOST \
    -u DOCKER_TLS_VERIFY \
    -u DOCKER_CERT_PATH \
    COMPOSE_DISABLE_ENV_FILE=1 \
    docker compose \
      --project-directory "$repo_dir" \
      -f "$selected_compose" \
      -p xuhua \
      "$@"
}

compose() {
  compose_with "$compose_file" "$@"
}

atomic_write_line() {
  local target="$1" value="$2" temporary
  temporary="$(mktemp "${target}.tmp.XXXXXX")" || return 1
  if printf '%s\n' "$value" >"$temporary" \
    && chmod 0640 "$temporary" \
    && mv -fT -- "$temporary" "$target"; then
    return 0
  fi
  rm -f -- "$temporary"
  return 1
}

atomic_copy() {
  local source="$1" target="$2" temporary
  temporary="$(mktemp "${target}.tmp.XXXXXX")" || return 1
  if cp -- "$source" "$temporary" \
    && chmod 0640 "$temporary" \
    && mv -fT -- "$temporary" "$target"; then
    return 0
  fi
  rm -f -- "$temporary"
  return 1
}

compose_snapshot_for() {
  printf '%s.%s\n' "$last_good_compose" "$1"
}

env_snapshot_for() {
  printf '%s.%s.%s.env\n' "$last_good_compose" "$1" "$2"
}

record_failure() {
  atomic_write_line "$failed_sha_file" "$commit_sha $env_revision $(date +%s)"
}

smoke_test() {
  python3 - "${XUHUA_APP_PORT:-5050}" "${XUHUA_REQUIRE_VOICE:-0}" <<'PY'
import json
import sys
import urllib.request

port = int(sys.argv[1])
require_voice = sys.argv[2] == "1"
base = f"http://127.0.0.1:{port}"

def read(path: str, timeout: float = 5.0) -> tuple[bytes, str]:
    with urllib.request.urlopen(base + path, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned {response.status}")
        return response.read(), response.headers.get_content_type()

health, _ = read("/healthz")
if json.loads(health).get("status") != "ok":
    raise RuntimeError("health endpoint did not report ok")

meta_raw, _ = read("/api/meta")
meta = json.loads(meta_raw)
if meta.get("item_count", 0) < 3000 or meta.get("category_count", 0) < 10:
    raise RuntimeError("knowledge base is incomplete")
if not meta.get("capabilities", {}).get("text_chat"):
    raise RuntimeError("text chat capability is unavailable")
if require_voice and not meta.get("capabilities", {}).get("realtime_voice"):
    raise RuntimeError("realtime voice is not configured")

categories_raw, _ = read("/api/categories")
if len(json.loads(categories_raw)) < 10:
    raise RuntimeError("category API is incomplete")

index, content_type = read("/")
if content_type != "text/html" or b'id="root"' not in index:
    raise RuntimeError("frontend entry page is unavailable")
PY
}

wait_for_healthy() {
  local running status
  for _ in $(seq 1 45); do
    running="$(docker inspect --format '{{ .State.Running }}' xuhua 2>/dev/null || true)"
    status="$(docker inspect --format '{{ if .State.Health }}{{ .State.Health.Status }}{{ end }}' xuhua 2>/dev/null || true)"
    if [[ "$running" != "true" || "$status" == "unhealthy" ]]; then
      return 1
    fi
    if [[ "$status" == "healthy" ]] && smoke_test; then
      return 0
    fi
    sleep 2
  done
  return 1
}

remember_success() {
  local compose_snapshot env_snapshot existing_good="" existing_env_revision=""
  local existing_compose="" existing_env=""
  compose_snapshot="$(compose_snapshot_for "$commit_sha")"
  env_snapshot="$(env_snapshot_for "$commit_sha" "$env_revision")"
  atomic_copy "$compose_file" "$compose_snapshot"
  atomic_copy "$env_file" "$env_snapshot"

  if [[ -r "$last_good_sha_file" ]]; then
    read -r existing_good existing_env_revision <"$last_good_sha_file" || true
    existing_compose="$(compose_snapshot_for "$existing_good")"
    existing_env="$(env_snapshot_for "$existing_good" "$existing_env_revision")"
    if [[ "$existing_good" =~ ^[0-9a-f]{40}$ \
      && -n "$existing_env_revision" \
      && ( "$existing_good" != "$commit_sha" || "$existing_env_revision" != "$env_revision" ) \
      && -f "$existing_compose" \
      && -f "$existing_env" ]]; then
      atomic_write_line "$previous_good_sha_file" "$existing_good $existing_env_revision"
    fi
  fi

  atomic_write_line "$last_good_sha_file" "$commit_sha $env_revision"
  rm -f -- "$failed_sha_file"
}

cleanup_old_artifacts() {
  local tag snapshot
  local keep_current="" keep_current_env="" keep_previous="" keep_previous_env=""
  local keep_current_compose="" keep_current_env_file=""
  local keep_previous_compose="" keep_previous_env_file=""

  if [[ -r "$last_good_sha_file" ]]; then
    read -r keep_current keep_current_env <"$last_good_sha_file" || true
  fi
  if [[ -r "$previous_good_sha_file" ]]; then
    read -r keep_previous keep_previous_env <"$previous_good_sha_file" || true
  fi

  while read -r tag; do
    if [[ "$tag" =~ ^xuhua:([0-9a-f]{40})$ \
      && "${BASH_REMATCH[1]}" != "$commit_sha" \
      && "${BASH_REMATCH[1]}" != "$previous_commit" \
      && "${BASH_REMATCH[1]}" != "$restore_commit" \
      && "${BASH_REMATCH[1]}" != "$keep_current" \
      && "${BASH_REMATCH[1]}" != "$keep_previous" ]]; then
      docker image rm "$tag" >/dev/null 2>&1 || true
    fi
  done < <(docker image ls xuhua --format '{{.Repository}}:{{.Tag}}')

  if [[ "$keep_current" =~ ^[0-9a-f]{40}$ ]]; then
    keep_current_compose="$(compose_snapshot_for "$keep_current")"
    if [[ -n "$keep_current_env" ]]; then
      keep_current_env_file="$(env_snapshot_for "$keep_current" "$keep_current_env")"
    fi
  fi
  if [[ "$keep_previous" =~ ^[0-9a-f]{40}$ ]]; then
    keep_previous_compose="$(compose_snapshot_for "$keep_previous")"
    if [[ -n "$keep_previous_env" ]]; then
      keep_previous_env_file="$(env_snapshot_for "$keep_previous" "$keep_previous_env")"
    fi
  fi

  for snapshot in "$last_good_compose".*; do
    [[ -e "$snapshot" ]] || continue
    if [[ "$snapshot" == "$keep_current_compose" \
      || "$snapshot" == "$keep_current_env_file" \
      || "$snapshot" == "$keep_previous_compose" \
      || "$snapshot" == "$keep_previous_env_file" \
      || "$snapshot" == "$restore_compose" \
      || "$snapshot" == "$restore_env" ]]; then
      continue
    fi
    rm -f -- "$snapshot" || true
  done
}

previous_was_healthy=0
restore_commit=""
restore_env_revision=""
restore_compose=""
restore_env=""

select_restore_target() {
  local candidate="" candidate_env_revision="" snapshot="" env_snapshot="" pointer=""
  local persisted_current="" persisted_env_revision="" persisted_snapshot="" persisted_env=""
  local state_error=0

  if [[ "$previous_was_healthy" == "1" \
    && "$previous_commit" =~ ^[0-9a-f]{40}$ \
    && -n "$previous_env_revision" \
    && ( "$previous_commit" != "$commit_sha" || "$previous_env_revision" != "$env_revision" ) ]] \
    && docker image inspect "xuhua:$previous_commit" >/dev/null 2>&1; then
    snapshot="$(compose_snapshot_for "$previous_commit")"
    if [[ ! -f "$snapshot" ]]; then
      [[ -f "$last_good_compose" ]] || return 2
      atomic_copy "$last_good_compose" "$snapshot" || return 2
    fi

    env_snapshot="$(env_snapshot_for "$previous_commit" "$previous_env_revision")"
    if [[ ! -f "$env_snapshot" ]]; then
      # Migration from the old SHA-only state is safe only when the external
      # env file still exactly matches the environment of the running container.
      [[ "$previous_env_revision" == "$env_revision" ]] || return 2
      atomic_copy "$env_file" "$env_snapshot" || return 2
    fi

    if [[ -r "$last_good_sha_file" ]]; then
      read -r persisted_current persisted_env_revision <"$last_good_sha_file" || true
    fi
    if [[ "$persisted_current" =~ ^[0-9a-f]{40}$ \
      && -n "$persisted_env_revision" \
      && ( "$persisted_current" != "$previous_commit" || "$persisted_env_revision" != "$previous_env_revision" ) ]]; then
      persisted_snapshot="$(compose_snapshot_for "$persisted_current")"
      persisted_env="$(env_snapshot_for "$persisted_current" "$persisted_env_revision")"
      if [[ -f "$persisted_snapshot" && -f "$persisted_env" ]]; then
        atomic_write_line "$previous_good_sha_file" "$persisted_current $persisted_env_revision" || return 2
      fi
    fi
    atomic_write_line "$last_good_sha_file" "$previous_commit $previous_env_revision" || return 2

    restore_commit="$previous_commit"
    restore_env_revision="$previous_env_revision"
    restore_compose="$snapshot"
    restore_env="$env_snapshot"
    return 0
  fi

  for pointer in "$last_good_sha_file" "$previous_good_sha_file"; do
    candidate=""
    candidate_env_revision=""
    [[ -r "$pointer" ]] || continue
    read -r candidate candidate_env_revision <"$pointer" || continue
    snapshot="$(compose_snapshot_for "$candidate")"
    env_snapshot="$(env_snapshot_for "$candidate" "$candidate_env_revision")"
    if [[ "$candidate" =~ ^[0-9a-f]{40}$ \
      && -n "$candidate_env_revision" \
      && ( "$candidate" != "$commit_sha" || "$candidate_env_revision" != "$env_revision" ) \
      && -f "$snapshot" \
      && -f "$env_snapshot" ]] \
      && docker image inspect "xuhua:$candidate" >/dev/null 2>&1; then
      restore_commit="$candidate"
      restore_env_revision="$candidate_env_revision"
      restore_compose="$snapshot"
      restore_env="$env_snapshot"
      return 0
    fi
    if [[ "$candidate" =~ ^[0-9a-f]{40}$ \
      && ( "$candidate" != "$commit_sha" || "$candidate_env_revision" != "$env_revision" ) ]]; then
      state_error=1
    fi
  done

  if [[ "$state_error" == "1" ]]; then
    return 2
  fi
  return 1
}

restore_previous() {
  if [[ "$restore_commit" =~ ^[0-9a-f]{40}$ \
    && -n "$restore_env_revision" \
    && -f "$restore_compose" \
    && -f "$restore_env" ]] \
    && docker image inspect "xuhua:$restore_commit" >/dev/null 2>&1; then
    echo "Restoring previously healthy deployment $restore_commit ($restore_env_revision)." >&2
    export XUHUA_COMMIT="$restore_commit"
    export XUHUA_ENV_FILE="$restore_env"
    export XUHUA_ENV_REVISION="$restore_env_revision"
    if compose_with "$restore_compose" up -d --no-build --force-recreate app && wait_for_healthy; then
      return 0
    fi
    echo "The previous deployment did not recover successfully." >&2
  fi

  echo "Stopping the failed candidate container." >&2
  docker stop --time 30 xuhua >/dev/null 2>&1 || true
  return 1
}

if [[ "$previous_commit" =~ ^[0-9a-f]{40}$ && "$container_running" == "true" && "$container_health" == "healthy" ]] && smoke_test; then
  previous_was_healthy=1
fi

if [[ "$previous_commit" == "$commit_sha" && "$previous_env_revision" == "$env_revision" && "$previous_was_healthy" == "1" ]]; then
  remember_success
  cleanup_old_artifacts
  exit 0
fi

if [[ "$recent_failure" == "1" && "$previous_was_healthy" == "1" ]]; then
  echo "Keeping the healthy running version while failed deployment $commit_sha ($env_revision) cools down." >&2
  exit 0
fi

restore_selection_status=0
select_restore_target || restore_selection_status=$?
if [[ "$restore_selection_status" == "2" ]]; then
  echo "Rollback state is incomplete; preserving the current container and refusing deployment." >&2
  exit 1
fi

if [[ "$previous_was_healthy" != "1" && "$restore_commit" =~ ^[0-9a-f]{40}$ ]]; then
  echo "No healthy container is running; restoring the last verified deployment before building." >&2
  restore_previous
  if [[ "$recent_failure" == "1" ]]; then
    exit 0
  fi
  previous_commit="$restore_commit"
  previous_env_revision="$restore_env_revision"
  previous_was_healthy=1
  export XUHUA_COMMIT="$commit_sha"
  export XUHUA_ENV_FILE="$env_file"
  export XUHUA_ENV_REVISION="$env_revision"
fi

activation_started=0
deployment_succeeded=0

handle_exit() {
  local status=$?
  trap - EXIT
  trap '' HUP INT TERM
  set +e
  set +u
  set +o pipefail
  if [[ "$status" != "0" && "$activation_started" == "1" && "$deployment_succeeded" != "1" ]]; then
    record_failure || true
    restore_previous || true
  fi
  exit "$status"
}

trap handle_exit EXIT
trap 'exit 129' HUP
trap 'exit 143' TERM
trap 'exit 130' INT

if ! compose config --quiet; then
  record_failure
  exit 1
fi

reuse_candidate_image=0
known_good_sha=""
known_good_env_revision=""
if [[ -r "$last_good_sha_file" ]]; then
  read -r known_good_sha known_good_env_revision <"$last_good_sha_file" || true
  if [[ "$known_good_sha" == "$commit_sha" ]] && docker image inspect "xuhua:$commit_sha" >/dev/null 2>&1; then
    reuse_candidate_image=1
  fi
fi

if [[ "$reuse_candidate_image" != "1" ]]; then
  if ! compose build --pull app; then
    record_failure
    exit 1
  fi
fi

activation_started=1
if [[ "$reuse_candidate_image" == "1" ]]; then
  compose up -d --remove-orphans --no-build --force-recreate app
else
  compose up -d --remove-orphans app
fi

if wait_for_healthy; then
  remember_success
  deployment_succeeded=1
  cleanup_old_artifacts
  exit 0
fi

docker logs --tail 120 xuhua >&2 || true
exit 1
