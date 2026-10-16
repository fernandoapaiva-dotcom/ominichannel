#!/bin/bash
# Watchdog do aprendizado de manuais da IA (rag-folder-watcher)
# Roda a cada 5 minutos via crontab

HEARTBEAT_FILE="/tmp/rag_watcher_heartbeat"
MAX_IDLE_SECONDS=480  # 8 minutos sem heartbeat = travado
LOG_FILE="/home/administrator/ominichannel/backend/logs/rag_watchdog.log"
mkdir -p /home/administrator/ominichannel/backend/logs

NOW=$(date +%s)

# Verifica se o arquivo de heartbeat existe
if [ -f "$HEARTBEAT_FILE" ]; then
    LAST_BEAT=$(stat -c %Y "$HEARTBEAT_FILE" 2>/dev/null || stat -f %m "$HEARTBEAT_FILE" 2>/dev/null)
    DIFF=$((NOW - LAST_BEAT))
    
    if [ $DIFF -gt $MAX_IDLE_SECONDS ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') [WATCHDOG ALERTA] rag-folder-watcher sem batimento ha $DIFF segundos (> $MAX_IDLE_SECONDS s). Reiniciando via PM2..." >> "$LOG_FILE"
        touch "$HEARTBEAT_FILE"
        pm2 restart rag-folder-watcher >> "$LOG_FILE" 2>&1
    fi
else
    # Se o arquivo ainda nao existe, cria
    touch "$HEARTBEAT_FILE"
fi
