# Vigia externo da VM (vm_watchdog)

Roda no **Windows que hospeda o VirtualBox**, fora da VM. Se a VM travar, ele reinicia a VM
inteira sozinho.

Foi criado depois de 12/10/2026, quando o kernel da VM travou (soft lockup + CIFS do
`\\192.168.15.16` sem responder) e o sistema ficou **15 horas fora do ar**. O vigia que já existia
([../health_watchdog/](../health_watchdog/)) roda *dentro* da VM, então travou junto e não reagiu.

## As três camadas de proteção

| Camada | Onde roda | Cobre | Tempo até agir |
|---|---|---|---|
| `health_watchdog.sh` | dentro da VM (cron) | backend lento ou travado | ~6 min → `pm2 restart` |
| `harden_guest.sh` | kernel da VM | kernel panic real + pasta do .16 com `nofail` | reinicia em 10s (só panic, não soft lockup) |
| **`vm_watchdog.ps1`** | PC hospedeiro (Agendador) | VM congelada, desligada, Guru Meditation, PC hospedeiro reiniciado | 4 min (VM travada) / 15 min (VM viva mas backend fora) |

## Como o vigia externo decide

A cada 1 minuto, ele:

1. Confere o estado da VM no VirtualBox. Se ela estiver **desligada, abortada ou em Guru
   Meditation**, liga a VM na hora (modo headless).
2. Descobre o IP da VM: primeiro o fixo do config, depois o informado pelo Guest Additions, depois
   o MAC na tabela ARP. A VM já trocou de .8 para .3 sozinha num reboot, então o vigia não depende
   de IP fixo.
3. Testa `http://IP:8000/api/v1/health` e a porta 22:
   - health OK → tudo certo;
   - sem health mas com SSH → a VM está viva e só o backend caiu. **Não reinicia a VM** (isso
     derrubaria junto a Evolution API e a sessão do WhatsApp, com risco de bloqueio do número):
     depois de 15 min sem o vigia interno resolver, só avisa uma vez. Opção
     `restart_vm_when_alive: true` no config volta ao comportamento antigo (desde 13/10/2026);
   - sem health e sem SSH → **VM travada**. Reinicia depois de 4 min.
4. Para reiniciar, primeiro tenta o desligamento ACPI ("apertar o botão"). Se a VM não desligar em
   90s (kernel travado não obedece), faz **reset forçado**.

Ele decide **só pela checagem local**. O `app.servweld.com.br` também é testado, mas só aparece no
log: se a internet cair, ele não reinicia uma VM que está saudável.

**Travas de segurança:** espera 15 min entre ações e faz no máximo 4 reinícios automáticos por
dia. Depois disso, só registra e avisa.

## Alertas

Todo evento vai para o `vm_watchdog.log` e para o **Visualizador de Eventos do Windows** (log
Application, fonte `OminiVmWatchdog`).

O WhatsApp usa a Evolution API, que roda **dentro** da VM. Com a VM travada não há como avisar,
então os alertas ficam numa fila e são enviados quando a VM volta. Para isso, a porta 8080 da
Evolution precisa estar acessível na rede local (hoje ela escuta só em `127.0.0.1`) e o
`alert.enabled` precisa estar `true` no `config.json`.

## Instalação no PC hospedeiro

1. Copie esta pasta `tools/vm_watchdog/` para o PC do VirtualBox (ex.: `C:\OminiVmWatchdog\`).
2. Abra o PowerShell **como Administrador**, logado com o **mesmo usuário que abre o
   VirtualBox** (as VMs são por usuário), e rode:
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\OminiVmWatchdog\install.ps1
   ```
3. Revise o `config.json` criado. O principal é o `vm_name`: deixe vazio se só existir uma VM, ou
   ponha o nome exato que aparece em `VBoxManage list vms`.
4. Teste uma vez na mão e veja o log:
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\OminiVmWatchdog\vm_watchdog.ps1
   Get-Content C:\OminiVmWatchdog\vm_watchdog.log -Tail 20
   ```

Como a tarefa também roda **na inicialização do Windows**, se o PC hospedeiro reiniciar (queda de
energia, Windows Update), a VM sobe sozinha sem ninguém precisar abrir o VirtualBox.

## Dentro da VM (uma vez)

```bash
sudo bash harden_guest.sh
```

Isso faz a VM reiniciar sozinha em caso de *kernel panic* real e coloca `nofail` nas montagens CIFS
do `/etc/fstab` (com backup), para a VM ligar mesmo com o `.16` fora do ar.

**De propósito, ele NÃO liga o `kernel.softlockup_panic`.** Em 12/10/2026 a VM registrava mais de
400 *soft lockups* por sessão, havia dias. A causa é o hospedeiro: o VirtualBox roda em modo NEM
sobre o Hyper-V, com 3 núcleos físicos para o Windows e mais 2 VMs. Com essa opção ligada, a VM
reiniciaria várias vezes por hora.

## Recomendado no roteador

Faça uma reserva de DHCP para o MAC da VM (`08:00:27:4b:9b:1b`), para ela sempre receber o mesmo
IP.

## Parâmetros (`config.json`)

| Chave | Padrão | O que é |
|---|---|---|
| `frozen_minutes` | 4 | VM sem SSH nem HTTP por esse tempo → reinicia |
| `backend_down_minutes` | 15 | VM viva mas backend fora por esse tempo → reinicia (o vigia interno tem prioridade) |
| `acpi_wait_seconds` | 90 | Espera do desligamento educado antes do reset forçado |
| `cooldown_minutes` | 15 | Intervalo mínimo entre ações |
| `max_actions_per_day` | 4 | Teto de reinícios automáticos por dia |
| `slow_threshold_seconds` | 8 | Health que responde 200 mas demora mais que isso conta como falha |
