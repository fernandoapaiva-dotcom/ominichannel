# Vigia de saúde do backend (health_watchdog.sh)

Script que roda no servidor (fora do processo do backend, via `cron`) checando se o site
responde. Se ficar sem resposta por várias checagens seguidas, avisa o Fernando por WhatsApp
e reinicia o backend sozinho — com limites de segurança pra nunca ficar reiniciando em loop.

Criado em 23/09/2026 depois de um travamento real (memória/CPU esgotados, requisições levando
minutos), em resposta ao pedido: *"o sistema tem que ter um plano de emergência pra sincronizar
mensagens que não chegaram, tem como criar um sensor quando cai e já começar sincronização?"*

## Como funciona

1. A cada 2 minutos, verifica `https://ominichannel.duckdns.org/` (timeout de 10s).
2. Só age depois de **3 falhas seguidas** (~4-6 min de indisponibilidade real) — nunca por uma
   soneca só.
3. Antes de reiniciar, manda um WhatsApp de aviso pro número do Fernando — **direto via
   Evolution API**, sem passar pelo backend (que é justamente o que pode estar travado).
4. Reinicia só o processo Python/FastAPI (`pm2 restart omini-backend`). **Nunca toca na conexão
   do WhatsApp** — o Evolution API roda num container Docker separado, que este script nunca
   reinicia.
5. Manda um segundo aviso quando confirma que voltou ao normal.
6. **Cooldown de 20 minutos**: não reinicia de novo antes disso, mesmo se continuar falhando —
   só avisa que o problema persiste.
7. **Teto de 3 reinícios automáticos por dia**: depois disso, só avisa (não reinicia mais
   sozinho) — evita loop de reinício por causa de um bug de deploy que um restart não resolve.

## Por que isso não tem risco de banimento do WhatsApp

- O `curl` de checagem de saúde nem toca no WhatsApp/Evolution API - só no nosso próprio site.
- O reinício do backend não desconecta nem reconecta a sessão do WhatsApp (Evolution API,
  que mantém essa sessão, roda num processo/container totalmente separado).
- O único envio de WhatsApp é o alerta pro próprio Fernando, e só acontece quando há um
  problema sustentado de verdade (gatilho de 3 falhas seguidas + cooldown de 20min) - não é
  um envio em massa nem repetitivo.

## Instalação (já feita em produção)

```bash
mkdir -p /home/ubuntu/ominichannel/tools/watchdog
cp health_watchdog.sh /home/ubuntu/ominichannel/tools/watchdog/
chmod +x /home/ubuntu/ominichannel/tools/watchdog/health_watchdog.sh

# Cron (a cada 2 minutos)
(crontab -l 2>/dev/null; echo '*/2 * * * * /home/ubuntu/ominichannel/tools/watchdog/health_watchdog.sh >/dev/null 2>&1') | crontab -
```

## Arquivos gerados em produção (não versionados)

- `/home/ubuntu/ominichannel/tools/watchdog/state.json` — contador de falhas seguidas, horário
  do último restart, lista de restarts de hoje (pro circuit breaker).
- `/home/ubuntu/ominichannel/tools/watchdog/watchdog.log` — histórico de tudo que o vigia fez.

## Ajustando os parâmetros

Todos os números-chave estão no topo do script:

| Variável | Valor | O que é |
|---|---|---|
| `CHECK_TIMEOUT` | 10s | Quanto tempo espera cada checagem antes de considerar falha |
| `FAILURES_TO_ACT` | 3 | Falhas seguidas necessárias antes de agir |
| `COOLDOWN_SECONDS` | 1200 (20min) | Intervalo mínimo entre reinícios automáticos |
| `MAX_RESTARTS_PER_DAY` | 3 | Teto de reinícios automáticos por dia |
