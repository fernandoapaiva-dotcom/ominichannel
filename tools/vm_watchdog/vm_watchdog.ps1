# Vigia EXTERNO da VM do OminiChannel (roda no Windows que hospeda o VirtualBox).
#
# Por que existe: o tools/health_watchdog/health_watchdog.sh roda DENTRO da VM. Quando o kernel
# da VM trava (soft lockup + CIFS do \\192.168.15.16 sem responder, 12/10/2026), o vigia interno
# trava junto e ninguem reage - ficamos 15h fora do ar. Este script fica do lado de fora e pode
# fazer o que o de dentro nao pode: reiniciar a VM inteira pelo VBoxManage.
#
# Camadas (cada uma so age se a anterior nao resolveu):
#   1. Backend lento/fora mas a VM viva (responde SSH) -> espera BACKEND_DOWN_MINUTES, porque o
#      vigia interno (pm2 restart) resolve isso sozinho em ~6min. So reinicia a VM se nao resolveu.
#   2. VM sem responder nem SSH nem HTTP (kernel travado) -> reinicia apos FROZEN_MINUTES.
#   3. VM desligada / abortada / Guru Meditation -> liga de novo na hora.
# Reinicio: primeiro desligamento ACPI (educado), se nao desligar em ACPI_WAIT_SECONDS -> reset forcado.
# Travas de seguranca: COOLDOWN entre acoes e teto de acoes por dia (depois so registra e avisa).
#
# Decide SO pela checagem local (IP da VM na rede). A checagem publica (app.servweld.com.br) e
# so informativa - se a internet cair, nao queremos reiniciar uma VM que esta saudavel.
#
# Agendado pelo install.ps1 (Agendador de Tarefas, a cada 1 minuto + na inicializacao do Windows).
# Arquivo mantido em ASCII de proposito: o PowerShell 5.1 le .ps1 sem BOM como ANSI.

$ErrorActionPreference = 'Continue'
$Dir = $PSScriptRoot
$ConfigFile = Join-Path $Dir 'config.json'
$StateFile = Join-Path $Dir 'state.json'
$LogFile = Join-Path $Dir 'vm_watchdog.log'

function Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    # Log nao cresce pra sempre: mantem as ultimas ~5000 linhas
    if ((Get-Item $LogFile).Length -gt 1MB) {
        $tail = Get-Content $LogFile -Tail 5000
        Set-Content -Path $LogFile -Value $tail -Encoding UTF8
    }
}

# Uma execucao por vez (o Agendador pode sobrepor se um reset demorar mais que 1 minuto)
$mutex = New-Object System.Threading.Mutex($false, 'Global\OminiVmWatchdog')
if (-not $mutex.WaitOne(0)) { exit 0 }

try {
    if (-not (Test-Path $ConfigFile)) { Log "config.json nao encontrado em $Dir - copie o config.example.json"; exit 1 }
    $cfg = Get-Content $ConfigFile -Raw | ConvertFrom-Json

    $VBox = $cfg.vboxmanage_path
    if (-not $VBox -or -not (Test-Path $VBox)) { $VBox = Join-Path $env:ProgramFiles 'Oracle\VirtualBox\VBoxManage.exe' }
    if (-not (Test-Path $VBox)) { Log "VBoxManage nao encontrado ($VBox)"; exit 1 }

    if (Test-Path $StateFile) { $state = Get-Content $StateFile -Raw | ConvertFrom-Json }
    else { $state = [pscustomobject]@{ first_failure = $null; last_action = $null; actions = @(); pending_alerts = @(); last_ip = $null } }
    foreach ($p in 'first_failure', 'last_action', 'actions', 'pending_alerts', 'last_ip') {
        if (-not ($state.PSObject.Properties.Name -contains $p)) { $state | Add-Member -NotePropertyName $p -NotePropertyValue $null }
    }
    if ($null -eq $state.actions) { $state.actions = @() }
    if ($null -eq $state.pending_alerts) { $state.pending_alerts = @() }

    function Save-State { $state | ConvertTo-Json -Depth 5 | Set-Content -Path $StateFile -Encoding UTF8 }

    function Queue-Alert([string]$text) {
        $state.pending_alerts = @($state.pending_alerts) + @("$text`n`n$(Get-Date -Format 'dd/MM HH:mm')")
        try { Write-EventLog -LogName Application -Source 'OminiVmWatchdog' -EventId 1000 -EntryType Warning -Message $text -ErrorAction Stop } catch {}
    }

    # Alertas vao por WhatsApp via Evolution API, que roda DENTRO da VM - entao com a VM travada
    # nao tem como avisar. Ficam na fila e saem assim que a VM volta (e ficam no log + Visualizador
    # de Eventos do Windows de qualquer forma).
    function Flush-Alerts([string]$ip) {
        if (-not $cfg.alert.enabled -or @($state.pending_alerts).Count -eq 0) { return }
        $url = $cfg.alert.evolution_url -replace '\{ip\}', $ip
        $remaining = @()
        foreach ($text in @($state.pending_alerts)) {
            try {
                $body = @{ number = $cfg.alert.number; text = $text } | ConvertTo-Json
                Invoke-RestMethod -Uri "$url/message/sendText/$($cfg.alert.instance)" -Method Post `
                    -Headers @{ apikey = $cfg.alert.api_key } -ContentType 'application/json; charset=utf-8' `
                    -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 15 | Out-Null
            } catch { $remaining += $text }
        }
        $state.pending_alerts = $remaining
    }

    # --- Descobre a VM -------------------------------------------------------------------------
    $vmName = $cfg.vm_name
    if (-not $vmName) {
        $vms = & $VBox list vms | ForEach-Object { if ($_ -match '^"(.+)"') { $Matches[1] } }
        if (@($vms).Count -ne 1) { Log "vm_name vazio no config.json e existem $(@($vms).Count) VMs - preencha o nome"; exit 1 }
        $vmName = @($vms)[0]
    }

    $info = & $VBox showvminfo $vmName --machinereadable 2>&1
    $vmState = ($info | Where-Object { $_ -match '^VMState=' }) -replace '^VMState="?([^"]*)"?$', '$1'
    $mac = ($info | Where-Object { $_ -match '^macaddress1=' }) -replace '^macaddress1="?([^"]*)"?$', '$1'
    # Nao conseguiu ler a VM (conta errada, VBoxSDS fora) - NUNCA tratar isso como "VM desligada"
    if (-not $vmState) { Log "Nao consegui ler o estado da VM '$vmName' - nada a fazer. Saida: $(($info | Select-Object -First 3) -join ' | ')"; exit 1 }

    # IP: tenta o fixo do config, senao o que o Guest Additions informa, senao procura o MAC na tabela ARP
    # (a VM ja trocou de .8 pra .3 sozinha num reboot - o vigia nao pode depender de IP fixo).
    function Resolve-VmIp {
        $candidates = @()
        if ($cfg.vm_ip) { $candidates += $cfg.vm_ip }
        $gp = & $VBox guestproperty get $vmName '/VirtualBox/GuestInfo/Net/0/V4/IP' 2>$null
        if ($gp -match 'Value:\s*([\d\.]+)') { $candidates += $Matches[1] }
        if ($mac -and $mac.Length -eq 12) {
            $macDash = (($mac -split '(..)' | Where-Object { $_ }) -join '-').ToLower()
            $arp = arp -a | Where-Object { $_ -match $macDash }
            if ($arp -and ($arp | Select-Object -First 1) -match '^\s*([\d\.]+)') { $candidates += $Matches[1] }
        }
        if ($state.last_ip) { $candidates += $state.last_ip }
        return $candidates | Select-Object -Unique
    }

    # HttpWebRequest direto e SEM proxy: no SRV-SERVWELD o Invoke-WebRequest do PS 5.1 dava falso
    # "sem resposta" (deteccao automatica de proxy/WPAD + TLS 1.2 desligado por padrao) com o
    # backend respondendo normal em 0,2s - e um falso negativo aqui REINICIA a VM a toa.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $script:lastHealthError = ''
    function Test-Health([string]$url) {
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $resp = $null
        try {
            $req = [Net.HttpWebRequest]::Create($url)
            $req.Proxy = $null
            $req.Timeout = $cfg.check_timeout_seconds * 1000
            $req.ReadWriteTimeout = $cfg.check_timeout_seconds * 1000
            $resp = $req.GetResponse()
            $sw.Stop()
            $ok = ([int]$resp.StatusCode -eq 200 -and $sw.Elapsed.TotalSeconds -le $cfg.slow_threshold_seconds)
            if (-not $ok) { $script:lastHealthError = "HTTP $([int]$resp.StatusCode) em $([math]::Round($sw.Elapsed.TotalSeconds,1))s" }
            return $ok
        } catch {
            $script:lastHealthError = $_.Exception.InnerException.Message
            if (-not $script:lastHealthError) { $script:lastHealthError = $_.Exception.Message }
            return $false
        } finally { if ($resp) { $resp.Close() } }
    }

    function Test-Port([string]$ip, [int]$port) {
        $c = New-Object Net.Sockets.TcpClient
        try { return $c.ConnectAsync($ip, $port).Wait(4000) -and $c.Connected } catch { return $false } finally { $c.Close() }
    }

    $now = Get-Date
    $today = $now.ToString('yyyy-MM-dd')
    $state.actions = @($state.actions | Where-Object { $_ -and ([datetime]$_) -gt $now.AddDays(-2) })
    $actionsToday = @($state.actions | Where-Object { $_.StartsWith($today) }).Count
    $inCooldown = $state.last_action -and (($now - [datetime]$state.last_action).TotalMinutes -lt $cfg.cooldown_minutes)

    function Register-Action { $state.last_action = $now.ToString('s'); $state.actions = @($state.actions) + @($now.ToString('s')); $state.first_failure = $null }

    # --- 3. VM desligada / abortada / Guru Meditation ------------------------------------------
    if ($vmState -ne 'running') {
        if ($vmState -eq 'starting' -or $vmState -eq 'restoring' -or $vmState -eq 'stopping') { Log "VM em transicao ($vmState) - aguardando"; Save-State; exit 0 }
        if ($inCooldown) { Log "VM em '$vmState' mas em cooldown - aguardando"; Save-State; exit 0 }
        Log "VM '$vmName' em estado '$vmState' - ligando"
        if ($vmState -eq 'gurumeditation' -or $vmState -eq 'paused' -or $vmState -eq 'stuck') { & $VBox controlvm $vmName poweroff 2>&1 | ForEach-Object { Log "  $_" }; Start-Sleep 5 }
        & $VBox startvm $vmName --type headless 2>&1 | ForEach-Object { Log "  $_" }
        Queue-Alert "OminiChannel - VM estava '$vmState' e foi ligada automaticamente pelo vigia externo."
        Register-Action; Save-State; exit 0
    }

    # --- Checagens -----------------------------------------------------------------------------
    $healthy = $false; $alive = $false; $usedIp = $null; $errors = @()
    foreach ($ip in (Resolve-VmIp)) {
        if (Test-Health ($cfg.health_url_local -replace '\{ip\}', $ip)) { $healthy = $true; $alive = $true; $usedIp = $ip; break }
        $errors += "$ip -> $script:lastHealthError"
        if (Test-Port $ip 22) { $alive = $true; $usedIp = $ip }
    }

    if ($healthy) {
        if ($state.first_failure) {
            $mins = [math]::Round(($now - [datetime]$state.first_failure).TotalMinutes)
            Log "RECUPERADO em $usedIp depois de ~$mins min com problema"
            Queue-Alert "OminiChannel - Sistema normalizado (ficou ~$mins min com problema). Vigia externo da VM."
        }
        if ($usedIp -ne $state.last_ip) { if ($state.last_ip) { Log "IP da VM mudou: $($state.last_ip) -> $usedIp (reserve o IP no DHCP do roteador)" }; $state.last_ip = $usedIp }
        $state.first_failure = $null
        Flush-Alerts $usedIp
        Save-State; exit 0
    }

    # --- Falhou ------------------------------------------------------------------------------
    if (-not $state.first_failure) { $state.first_failure = $now.ToString('s') }
    $downMin = ($now - [datetime]$state.first_failure).TotalMinutes
    $publicOk = Test-Health $cfg.health_url_public
    $limit = if ($alive) { $cfg.backend_down_minutes } else { $cfg.frozen_minutes }
    $kind = if ($alive) { 'backend sem resposta, VM viva (SSH ok)' } else { 'VM TRAVADA (sem SSH nem HTTP)' }
    Log ("Falha: {0} ha {1:N1} min (limite {2} min) | publico={3} | {4}" -f $kind, $downMin, $limit, $publicOk, ($errors -join '; '))

    if ($downMin -lt $limit) { Save-State; exit 0 }
    if ($inCooldown) { Log "Sustentado, mas em cooldown desde $($state.last_action) - nao reinicia de novo ainda"; Save-State; exit 0 }
    if ($actionsToday -ge $cfg.max_actions_per_day) {
        Log "Teto de $($cfg.max_actions_per_day) reinicios automaticos hoje atingido - precisa de intervencao manual"
        if ($downMin -lt $limit + 2) { Queue-Alert "OminiChannel - CAIU DE NOVO ($kind) e ja bati o teto de reinicios automaticos hoje. Precisa de atencao manual." }
        Save-State; exit 0
    }

    # --- Age: ACPI primeiro, reset forcado se nao obedecer --------------------------------------
    Log "SUSTENTADO ($kind, $([math]::Round($downMin)) min) - reiniciando a VM '$vmName'"
    & $VBox controlvm $vmName acpipowerbutton 2>&1 | ForEach-Object { Log "  $_" }
    $deadline = (Get-Date).AddSeconds($cfg.acpi_wait_seconds)
    do {
        Start-Sleep 5
        $st = ((& $VBox showvminfo $vmName --machinereadable) | Where-Object { $_ -match '^VMState=' }) -replace '^VMState="?([^"]*)"?$', '$1'
    } while ($st -eq 'running' -and (Get-Date) -lt $deadline)

    if ($st -eq 'running') {
        Log "Nao desligou pelo ACPI em $($cfg.acpi_wait_seconds)s (kernel travado) - RESET forcado"
        & $VBox controlvm $vmName reset 2>&1 | ForEach-Object { Log "  $_" }
    } else {
        Log "Desligou pelo ACPI ($st) - ligando de novo"
        Start-Sleep 3
        & $VBox startvm $vmName --type headless 2>&1 | ForEach-Object { Log "  $_" }
    }
    Queue-Alert "OminiChannel - Reiniciei a VM automaticamente ($kind por $([math]::Round($downMin)) min). Vigia externo da VM."
    Register-Action; Save-State
}
finally {
    $mutex.ReleaseMutex()
}
