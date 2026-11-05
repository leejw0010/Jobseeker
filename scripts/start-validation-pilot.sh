#!/usr/bin/env bash
# Human-operated localhost pilot; creates fresh storage every time. No external paid API.
set -euo pipefail
umask 077
pilot_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# Application/Vite dotenv loaders must never read a developer's private settings.
pilot_has_dotenv=false
[[ ! -e "$pilot_repo/backend/.env" ]] || pilot_has_dotenv=true
for pilot_file in "$pilot_repo"/web/.env*; do
  [[ ! -e "$pilot_file" || "$pilot_file" == *.example ]] || pilot_has_dotenv=true
done
if [[ "$pilot_has_dotenv" == true ]]; then
  echo 'Refusing to start beside private dotenv files; use the isolated validation worktree without copied dotenv files.' >&2
  exit 2
fi
pilot_root=$(mktemp -d /tmp/jobseeker-human-pilot-XXXXXXXX)
pilot_root=$(realpath "$pilot_root")
case "$pilot_root" in /tmp/jobseeker-human-pilot-*) ;; *) echo 'Pilot directory must be a new directory directly under /tmp.' >&2; exit 2;; esac
mkdir "$pilot_root/recordings"
pilot_revision=$(git -C "$pilot_repo" rev-parse HEAD)
pilot_dirty=false
if [[ -n $(git -C "$pilot_repo" status --porcelain --untracked-files=normal) ]]; then pilot_dirty=true; fi
printf 'Fresh isolated pilot: %s\nAPI: http://127.0.0.1:8013\nWeb: http://127.0.0.1:5181\nCode: %s dirty=%s\n' "$pilot_root" "$pilot_revision" "$pilot_dirty"
if [[ ${1:-} == --check ]]; then rmdir "$pilot_root/recordings" "$pilot_root"; exit 0; fi
if [[ $# -ne 0 ]]; then echo 'Usage: scripts/start-validation-pilot.sh [--check]' >&2; exit 2; fi
pilot_api_pid='';pilot_web_pid=''
pilot_cleanup() {
  trap - EXIT INT TERM
  [[ -z "$pilot_web_pid" ]] || kill "$pilot_web_pid" 2>/dev/null || true
  [[ -z "$pilot_api_pid" ]] || kill "$pilot_api_pid" 2>/dev/null || true
  [[ -z "$pilot_web_pid" ]] || wait "$pilot_web_pid" 2>/dev/null || true
  [[ -z "$pilot_api_pid" ]] || wait "$pilot_api_pid" 2>/dev/null || true
  printf 'Owned servers stopped. Pilot DB/recordings remain only in %s; remove that directory after reviewing the pilot.\n' "$pilot_root"
}
trap pilot_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
(
 cd "$pilot_repo/backend"
 exec env -i PATH="$PATH" HOME="$HOME" LANG="${LANG:-C.UTF-8}" APP_ENV=test AUTH_DISABLED=true \
  OPENAI_API_KEY= SUPABASE_URL= SUPABASE_SERVICE_ROLE_KEY= SUPABASE_JWT_SECRET= \
  DATABASE_URL="sqlite:///$pilot_root/pilot.db" RECORDINGS_DIR="$pilot_root/recordings" \
  PRACTICE_INSIGHTS_ENABLED=true PRACTICE_COMPETENCY_EVIDENCE_ENABLED=false \
  STT_PROVIDER=local LOCAL_STT_MODEL=base LOCAL_STT_DEVICE=cpu LOCAL_STT_COMPUTE_TYPE=int8 LOCAL_STT_CPU_THREADS=2 \
  LOCAL_STT_ALLOW_DOWNLOAD=false HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  CORS_ORIGINS=http://127.0.0.1:5181,http://localhost:5181 \
  "$pilot_repo/backend/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8013
) >"$pilot_root/api.log" 2>&1 &
pilot_api_pid=$!
(
 cd "$pilot_repo/web"
 exec env -i PATH="$PATH" HOME="$HOME" LANG="${LANG:-C.UTF-8}" APP_ENV=test AUTH_DISABLED=true \
  VITE_API_URL=http://127.0.0.1:8013 VITE_E2E_FAKE_FACE=false VITE_GAZE_LAB=true \
  VITE_VALIDATION_CODE_VERSION="$pilot_revision" VITE_VALIDATION_DIRTY="$pilot_dirty" \
  node "$pilot_repo/web/node_modules/vite/bin/vite.js" --host 127.0.0.1 --port 5181 --strictPort --mode validation
) >"$pilot_root/web.log" 2>&1 &
pilot_web_pid=$!
# Fail fast if a port is occupied or a dependency is missing; wait only for owned servers.
sleep 2
kill -0 "$pilot_api_pid" "$pilot_web_pid"
printf 'Use disposable answers only; grant media consent yourself. Logs: %s\nStop with Ctrl-C.\n' "$pilot_root"
wait -n "$pilot_api_pid" "$pilot_web_pid"
