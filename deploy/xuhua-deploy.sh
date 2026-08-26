#!/usr/bin/env bash
set -Eeuo pipefail

umask 027

repo_dir="${XUHUA_REPO_DIR:-/opt/xuhua/repo}"
env_file="${XUHUA_ENV_FILE:-/etc/xuhua/xuhua.env}"
lock_file="${XUHUA_LOCK_FILE:-/var/lib/xuhua/deploy.lock}"
failed_sha_file="${XUHUA_FAILED_SHA_FILE:-/var/lib/xuhua/failed-sha}"
last_good_compose="${XUHUA_LAST_GOOD_COMPOSE:-/var/lib/xuhua/last-good-compose.yaml}"
failure_cooldown="${XUHUA_FAILURE_COOLDOWN:-600}"
compose_file="$repo_dir/compose.yaml"
expected_origin="https://github.com/RinoPaw/xuhua.git"

if [[ ! "$failure_cooldown" =~ ^[0-9]+$ ]]; then
  failure_cooldown=600
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

if [[ "$(git remote get-url origin)" != "$expected_origin" ]]; then
  echo "Unexpected Git origin; refusing to deploy." >&2
  exit 1
fi

if [[ -n "$(git status --porcelain=v1 --untracked-files=all)" ]]; then
  echo "Deployment checkout is dirty; refusing to overwrite local changes." >&2
  exit 1
fi

if [[ -e .env || -e compose.override.yml || -e compose.override.yaml ]]; then
  echo "Repository-local deployment overrides are not permitted." >&2
  exit 1
fi

git fetch --prune origin main
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
container_running="$(docker inspect --format '{{ .State.Running }}' xuhua 2>/dev/null || true)"
container_health="$(docker inspect --format '{{ if .State.Health }}{{ .State.Health.Status }}{{ end }}' xuhua 2>/dev/null || true)"

if read -r failed_sha failed_at <"$failed_sha_file" 2>/dev/null; then
  now="$(date +%s)"
  if [[ "$failed_sha" == "$commit_sha" && "$failed_at" =~ ^[0-9]+$ && $((now - failed_at)) -lt "$failure_cooldown" ]]; then
    echo "Skipping recently failed commit $commit_sha until its cooldown expires." >&2
    exit 0
  fi
fi

export XUHUA_COMMIT="$commit_sha"
export XUHUA_ENV_FILE="$env_file"

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

record_failure() {
  printf '%s %s\n' "$commit_sha" "$(date +%s)" >"$failed_sha_file"
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
  cp "$compose_file" "$last_good_compose"
  chmod 0640 "$last_good_compose"
  : >"$failed_sha_file"
}

cleanup_old_images() {
  local tag
  while read -r tag; do
    if [[ "$tag" =~ ^xuhua:([0-9a-f]{40})$ && "${BASH_REMATCH[1]}" != "$commit_sha" && "${BASH_REMATCH[1]}" != "$previous_commit" ]]; then
      docker image rm "$tag" >/dev/null 2>&1 || true
    fi
  done < <(docker image ls xuhua --format '{{.Repository}}:{{.Tag}}')
}

restore_previous() {
  if [[ -f "$last_good_compose" && "$previous_commit" =~ ^[0-9a-f]{40}$ && "$previous_commit" != "$commit_sha" ]] && docker image inspect "xuhua:$previous_commit" >/dev/null 2>&1; then
    echo "Restoring previously healthy image $previous_commit." >&2
    export XUHUA_COMMIT="$previous_commit"
    if compose_with "$last_good_compose" up -d --no-build --force-recreate app && wait_for_healthy; then
      return 0
    fi
    echo "The previous image did not recover successfully." >&2
    return 1
  fi

  if [[ -z "$previous_commit" ]]; then
    compose stop app >/dev/null 2>&1 || true
  fi
  return 1
}

if [[ "$previous_commit" == "$commit_sha" && "$container_running" == "true" && "$container_health" == "healthy" ]] && smoke_test; then
  remember_success
  exit 0
fi

if ! compose config --quiet; then
  record_failure
  exit 1
fi

if ! compose build --pull app; then
  record_failure
  exit 1
fi

if ! compose up -d --remove-orphans app; then
  record_failure
  restore_previous || true
  exit 1
fi

if wait_for_healthy; then
  remember_success
  cleanup_old_images
  exit 0
fi

docker logs --tail 120 xuhua >&2 || true
record_failure
restore_previous || true
exit 1
