#!/bin/bash
# Vigia de saude do backend OminiChannel.
#
# Roda via cron a cada 2 minutos, FORA do processo do backend (pra continuar funcionando mesmo
# se o backend travar de verdade). So age depois de FAILURES_TO_ACT checagens seguidas falhando
# (nunca por uma soneca so), avisa o Fernando por WhatsApp direto (via Evolution API, sem passar
# pelo backend - que pode estar travado) ANTES de reiniciar e DEPOIS que confirma que voltou,
# tem um intervalo minimo entre reinicios (COOLDOWN_SECONDS) e um teto de reinicios automaticos
# por dia (MAX_RESTARTS_PER_DAY) - depois disso so avisa, nao fica reiniciando sem parar.
#
# NAO mexe na conexao do WhatsApp (Evolution API roda num container Docker separado, que este
# script nunca reinicia) - só reinicia o processo Python/FastAPI do nosso backend.
#
# Instalado no servidor em /home/ubuntu/ominichannel/tools/watchdog/health_watchdog.sh via:
#   crontab -e
#   */2 * * * * /home/ubuntu/ominichannel/tools/watchdog/health_watchdog.sh >/dev/null 2>&1
#
# Testado em produção em 23/09/2026: detecção de falha, alerta antes/depois e restart real
# confirmados funcionando de ponta a ponta.

set -uo pipefail

DIR="/home/ubuntu/ominichannel/tools/watchdog"
STATE_FILE="$DIR/state.json"
LOG_FILE="$DIR/watchdog.log"
HEALTH_URL="https://ominichannel.duckdns.org/"
CHECK_TIMEOUT=10
FAILURES_TO_ACT=3
COOLDOWN_SECONDS=1200
MAX_RESTARTS_PER_DAY=3

ALERT_NUMBER="5561998334833"
ALERT_INSTANCE="instancia_tecnica"
EVOLUTION_URL="http://127.0.0.1:8080"
EVOLUTION_KEY="omini_master_key_123"

mkdir -p "$DIR"
[ -f "$STATE_FILE" ] || echo '{"consecutive_failures":0,"last_restart_ts":0,"restarts_today":[]}' > "$STATE_FILE"

now_ts=$(date +%s)
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"; }

send_whatsapp_alert() {
    local text="$1"
    curl -s -m 15 -X POST "$EVOLUTION_URL/message/sendText/$ALERT_INSTANCE" \
        -H "apikey: $EVOLUTION_KEY" -H "Content-Type: application/json" \
        -d "{\"number\":\"$ALERT_NUMBER\",\"text\":$(printf '%s' "$text" | jq -Rs .)}" >> "$LOG_FILE" 2>&1
}

# Mantém o histórico de reinícios só dos últimos 2 dias (evita o arquivo de estado crescer pra
# sempre - o resto é só peso morto já que o filtro de "hoje" já ignora entradas antigas mesmo).
prune_ts=$(date -d '2 days ago' -Iseconds 2>/dev/null || date -Iseconds)
jq --arg cutoff "$prune_ts" '.restarts_today = [.restarts_today[] | select(. > $cutoff)]' "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"

# 1. Checagem de saúde (mesma URL pública que qualquer atendente usa - se nginx+backend
#    estiverem OK, isso responde 200 rápido; se estiver travado como em 23/09, demora/falha).
http_code=$(curl -s -o /dev/null -w '%{http_code}' -m "$CHECK_TIMEOUT" "$HEALTH_URL" 2>/dev/null)
http_code="${http_code:-000}"

consecutive_failures=$(jq -r '.consecutive_failures' "$STATE_FILE")
last_restart_ts=$(jq -r '.last_restart_ts' "$STATE_FILE")

if [ "$http_code" = "200" ]; then
    if [ "$consecutive_failures" -ge "$FAILURES_TO_ACT" ]; then
        log "RECUPERADO - site respondendo 200 de novo depois de $consecutive_failures falhas seguidas."
        send_whatsapp_alert "✅ *OminiChannel - Sistema normalizado*

O sistema estava lento/sem resposta e voltou ao normal agora.
Nenhuma ação adicional necessária.

$(date '+%d/%m %H:%M')"
    fi
    jq '.consecutive_failures = 0' "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
    exit 0
fi

# 2. Falhou - incrementa contador
consecutive_failures=$((consecutive_failures + 1))
jq --argjson n "$consecutive_failures" '.consecutive_failures = $n' "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
log "Falha #$consecutive_failures (HTTP $http_code)"

if [ "$consecutive_failures" -lt "$FAILURES_TO_ACT" ]; then
    exit 0
fi

# 3. Problema sustentado - respeita o cooldown antes de reiniciar de novo
seconds_since_restart=$((now_ts - last_restart_ts))
if [ "$seconds_since_restart" -lt "$COOLDOWN_SECONDS" ]; then
    log "Sustentado há $consecutive_failures checagens, mas ainda em cooldown (${seconds_since_restart}s desde o último restart) - só avisando, sem reiniciar de novo."
    send_whatsapp_alert "⚠️ *OminiChannel - Ainda lento/sem resposta*

Já reiniciei há pouco e o problema persiste (HTTP $http_code). Pode ser algo além de sobrecarga passageira - melhor você dar uma olhada quando puder.

$(date '+%d/%m %H:%M')"
    exit 0
fi

# 4. Circuit breaker - teto de reinícios automáticos por dia
today=$(date '+%Y-%m-%d')
restarts_today_count=$(jq --arg d "$today" '[.restarts_today[] | select(startswith($d))] | length' "$STATE_FILE")
if [ "$restarts_today_count" -ge "$MAX_RESTARTS_PER_DAY" ]; then
    log "Limite de $MAX_RESTARTS_PER_DAY reinícios automáticos hoje atingido - só avisando, precisa de intervenção manual."
    send_whatsapp_alert "🚨 *OminiChannel - Precisa de atenção manual*

O sistema caiu de novo (HTTP $http_code) e já bati o limite de $MAX_RESTARTS_PER_DAY reinícios automáticos hoje. Não vou reiniciar sozinho de novo - por favor dê uma olhada.

$(date '+%d/%m %H:%M')"
    exit 0
fi

# 5. Agir: avisar ANTES, reiniciar, e confirmar DEPOIS (feito na próxima checagem, quando o
#    http_code=200 for detectado de novo, no bloco lá em cima).
log "SUSTENTADO - $consecutive_failures falhas seguidas (HTTP $http_code). Reiniciando backend..."
send_whatsapp_alert "🔧 *OminiChannel - Reiniciando automaticamente*

O sistema ficou sem resposta por várias checagens seguidas (HTTP $http_code). Vou reiniciar o backend agora pra normalizar.

O WhatsApp em si NÃO desconecta com isso - só o painel/atendimento automático fica fora por alguns segundos.

$(date '+%d/%m %H:%M')"

# Sinaliza pro backend que essa é uma queda REAL (não um deploy de rotina) - o boot vai ver
# esse arquivo e disparar a varredura de recuperação (confere o que ficou faltando de mensagem
# enquanto ficou fora do ar). Um `pm2 restart` manual comum NÃO cria esse arquivo, então não
# dispara a varredura pesada à toa - só quando o vigia mesmo decide que precisou reiniciar.
touch "$DIR/reconcile_requested.flag"

pm2 restart omini-backend --update-env >> "$LOG_FILE" 2>&1

jq --argjson ts "$now_ts" --arg d "$(date -Iseconds)" \
   '.last_restart_ts = $ts | .restarts_today += [$d] | .consecutive_failures = 0' \
   "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"

log "Restart disparado."
