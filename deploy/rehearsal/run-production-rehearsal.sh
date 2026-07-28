#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)"
CANDIDATE_IMAGE="${REHEARSAL_CANDIDATE_IMAGE:-tocadocoelho-web:f85-candidate}"
PREVIOUS_IMAGE="${REHEARSAL_PREVIOUS_IMAGE:-tocadocoelho-web:f85-previous}"
PROJECT_NAME="${REHEARSAL_PROJECT_NAME:-toca-f85-${GITHUB_RUN_ID:-$$}}"
HTTP_PORT="${REHEARSAL_HTTP_PORT:-18080}"
HTTPS_PORT="${REHEARSAL_HTTPS_PORT:-18443}"
BUILD_SHA="${REHEARSAL_BUILD_SHA:-unknown}"

case "$CANDIDATE_IMAGE" in
    tocadocoelho-web:*) CANDIDATE_TAG="${CANDIDATE_IMAGE#tocadocoelho-web:}" ;;
    *) echo "Imagem candidata deve usar o repositório tocadocoelho-web." >&2; exit 2 ;;
esac
case "$PREVIOUS_IMAGE" in
    tocadocoelho-web:*) PREVIOUS_TAG="${PREVIOUS_IMAGE#tocadocoelho-web:}" ;;
    *) echo "Imagem anterior deve usar o repositório tocadocoelho-web." >&2; exit 2 ;;
esac

case "$PROJECT_NAME" in
    toca-f85-*) ;;
    *) echo "REHEARSAL_PROJECT_NAME fora do namespace toca-f85-*." >&2; exit 2 ;;
esac
case "$PROJECT_NAME" in
    *[!a-z0-9-]*) echo "Nome de projeto do ensaio inválido." >&2; exit 2 ;;
esac
case "$HTTP_PORT:$HTTPS_PORT" in
    *[!0-9:]*) echo "Portas do ensaio devem ser numéricas." >&2; exit 2 ;;
esac

docker image inspect "$CANDIDATE_IMAGE" >/dev/null
docker image inspect "$PREVIOUS_IMAGE" >/dev/null

work_dir="$(mktemp -d)"
env_file="$work_dir/rehearsal.env"
cert_dir="$work_dir/certs"
mkdir -p "$cert_dir"
chmod 700 "$work_dir" "$cert_dir"

compose() {
    docker compose \
        --project-name "$PROJECT_NAME" \
        --env-file "$env_file" \
        --file "$ROOT_DIR/docker-compose.production.yml" \
        "$@"
}

cleanup() {
    status="$1"
    trap - EXIT HUP INT TERM
    if [ -f "$env_file" ]; then
        if [ "$status" -ne 0 ]; then
            compose ps >&2 || true
            compose logs --no-color >&2 || true
        fi
        compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    fi
    rm -rf "$work_dir"
    exit "$status"
}
trap 'cleanup $?' EXIT
trap 'exit 130' HUP INT TERM

openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -subj '/CN=localhost' \
    -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1' \
    -keyout "$cert_dir/privkey.pem" \
    -out "$cert_dir/fullchain.pem" >/dev/null 2>&1
chmod 600 "$cert_dir/privkey.pem" "$cert_dir/fullchain.pem"

waha_key='f85-disposable-waha-api-key-with-more-than-32-characters'
waha_hmac='f85-disposable-webhook-hmac-with-more-than-32-characters'
waha_digest="$(printf '%s' "$waha_key" | sha512sum | awk '{print $1}')"

cat > "$env_file" <<EOF
TOCA_ENV=production
TOCA_AUTH_ENABLED=1
TOCA_COOKIE_SECURE=1
TOCA_COOKIE_SAMESITE=Lax
TOCA_TRUST_PROXY=1
TOCA_RUN_MIGRATIONS_ON_STARTUP=0
TOCA_LOG_FORMAT=json
TOCA_LOG_FILE_ENABLED=0
TOCA_MULTIWORKER_JOBS_ENABLED=1
TOCA_DISABLE_BG_JOBS=1
WEB_CONCURRENCY=2
TOCA_IMAGE_TAG=$CANDIDATE_TAG
TOCA_BUILD_SHA=$BUILD_SHA
TOCA_BUILD_VERSION=f85-candidate
TOCA_HTTP_PORT=$HTTP_PORT
TOCA_HTTPS_PORT=$HTTPS_PORT
TOCA_TIMEZONE=America/Sao_Paulo
SECRET_KEY=f85-disposable-session-secret-with-more-than-32-characters
POSTGRES_DB=toca
POSTGRES_USER=toca
POSTGRES_PASSWORD=f85-disposable-postgres-password
DATABASE_URL=postgresql://toca:f85-disposable-postgres-password@postgres:5432/toca
BACKUP_INTERVAL_HOURS=24
BACKUP_RETENTION_DAYS=14
OUTLOOK_GRAPH_TENANT_ID=organizations
OUTLOOK_GRAPH_CLIENT_ID=00000000-0000-0000-0000-000000000085
OUTLOOK_GRAPH_LOGIN_REDIRECT_URI=https://localhost:$HTTPS_PORT/api/auth/callback
OUTLOOK_GRAPH_REDIRECT_URI=https://localhost:$HTTPS_PORT/api/outlook/oauth/callback
OUTLOOK_GRAPH_LOGIN_SCOPE=openid profile email User.Read
OUTLOOK_GRAPH_SCOPE=offline_access Mail.Read Mail.Send User.Read
WAHA_API_KEY=$waha_key
WAHA_API_KEY_HASH=sha512:$waha_digest
WAHA_WEBHOOK_HMAC_KEY=$waha_hmac
WAHA_SESSION_NAME=f85
TLS_CERTS_DIR=$cert_dir
EOF
chmod 600 "$env_file"

compose up -d --no-build

ready_url="https://127.0.0.1:$HTTPS_PORT/readyz"
for attempt in $(seq 1 120); do
    if curl --insecure --fail --silent "$ready_url" >/dev/null; then
        break
    fi
    if [ "$attempt" -eq 120 ]; then
        compose ps
        compose logs
        exit 1
    fi
    sleep 2
done

test "$(compose ps -a --format json migrate | grep -c '\"ExitCode\":0')" -ge 1
test "$(compose logs web 2>&1 | grep -c 'Booting worker with pid')" -ge 2
compose logs web 2>&1 | grep -q '"event":"http_request"'

candidate_revision="$(
    docker image inspect --format \
        '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
        "$CANDIDATE_IMAGE"
)"
test "$candidate_revision" = "$BUILD_SHA"

test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
    "http://127.0.0.1:$HTTP_PORT/healthz")" = "308"
curl --insecure --fail --silent \
    --header 'X-Request-ID: f85-edge-request-0001' \
    --dump-header "$work_dir/ready.headers" \
    "$ready_url" >/dev/null
grep -qi '^X-Request-ID: f85-edge-request-0001' "$work_dir/ready.headers"

test "$(curl --insecure --silent --output "$work_dir/unauth.json" \
    --write-out '%{http_code}' \
    "https://127.0.0.1:$HTTPS_PORT/api/admin/jobs/status")" = "401"
grep -q '"error_type":"auth_required"' "$work_dir/unauth.json"

curl --insecure --silent \
    --cookie-jar "$work_dir/cookies.txt" \
    --dump-header "$work_dir/login.headers" \
    --output /dev/null \
    "https://127.0.0.1:$HTTPS_PORT/api/auth/login"
grep -qi '^Location: https://login.microsoftonline.com/organizations/' \
    "$work_dir/login.headers"
grep -qi 'code_challenge=' "$work_dir/login.headers"

curl --insecure --fail --silent \
    --cookie "$work_dir/cookies.txt" \
    --request POST \
    "https://127.0.0.1:$HTTPS_PORT/api/auth/logout" \
    | grep -q '"ok":true'

if compose port waha 3000 2>/dev/null | grep -q .; then
    echo "WAHA publicou porta no host durante o ensaio." >&2
    exit 1
fi
compose exec -T waha node -e \
    "require('http').get('http://127.0.0.1:3000/health',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"
compose exec -T waha node -e \
    "const crypto=require('crypto'),http=require('http');const body=JSON.stringify({event:'message.any',session:'f85',payload:{from:'5511000000000@c.us',fromMe:false,body:'rehearsal',timestamp:1750000000}});const sig=crypto.createHmac('sha512',process.env.WHATSAPP_HOOK_HMAC_KEY).update(body).digest('hex');const req=http.request(process.env.WHATSAPP_HOOK_URL,{method:'POST',headers:{'Content-Type':'application/json','Content-Length':Buffer.byteLength(body),'X-Webhook-Hmac':sig,'X-Webhook-Hmac-Algorithm':'sha512'}},res=>process.exit(res.statusCode===200?0:1));req.on('error',()=>process.exit(1));req.end(body);"

for attempt in $(seq 1 30); do
    if compose exec -T postgres-backup test -s /backups/.last-success; then
        break
    fi
    if [ "$attempt" -eq 30 ]; then
        compose logs postgres-backup
        exit 1
    fi
    sleep 2
done
compose exec -T postgres-backup sh -c \
    'test "$(find /backups -name "tocadocoelho-*.dump" | wc -l)" -ge 1'

# Rollback real de imagem: recria somente o web com a imagem da Live anterior,
# confirma o ID em execução e volta ao candidato. O schema permanece aditivo e
# compatível; migrations nunca são revertidas automaticamente.
export TOCA_IMAGE_TAG="$PREVIOUS_TAG"
compose up -d --no-deps --no-build --force-recreate web
for attempt in $(seq 1 60); do
    if curl --insecure --fail --silent "$ready_url" >/dev/null; then break; fi
    if [ "$attempt" -eq 60 ]; then compose logs web; exit 1; fi
    sleep 2
done
web_container="$(compose ps -q web)"
test "$(docker inspect --format '{{.Image}}' "$web_container")" = \
    "$(docker image inspect --format '{{.Id}}' "$PREVIOUS_IMAGE")"

export TOCA_IMAGE_TAG="$CANDIDATE_TAG"
compose up -d --no-deps --no-build --force-recreate web
for attempt in $(seq 1 60); do
    if curl --insecure --fail --silent "$ready_url" >/dev/null; then break; fi
    if [ "$attempt" -eq 60 ]; then compose logs web; exit 1; fi
    sleep 2
done
web_container="$(compose ps -q web)"
test "$(docker inspect --format '{{.Image}}' "$web_container")" = \
    "$(docker image inspect --format '{{.Id}}' "$CANDIDATE_IMAGE")"

printf 'production_rehearsal_ok project=%s build_sha=%s\n' \
    "$PROJECT_NAME" "$BUILD_SHA"
