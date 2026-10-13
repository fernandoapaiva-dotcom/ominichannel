# Instala o vigia externo da VM no Windows que roda o VirtualBox.
# Rodar no PowerShell COMO ADMINISTRADOR, logado com o MESMO usuario que abre o VirtualBox
# (as VMs do VirtualBox sao por usuario - outro usuario nao enxerga a VM):
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# Cria 2 tarefas no Agendador:
#   OminiChannel - Vigia da VM      -> roda o vm_watchdog.ps1 a cada 1 minuto, sempre
#   (a mesma tarefa tambem dispara na inicializacao do Windows, entao se o PC hospedeiro reiniciar
#    - queda de energia, Windows Update - a VM e ligada sozinha, sem ninguem precisar abrir nada)

#
# -User: conta dona da VM, se o instalador for rodado por outra conta (ex.: SYSTEM, num deploy
# remoto). No SRV-SERVWELD a VM e do SERVWELD\Administrator.
param([string]$User = "$env:USERDOMAIN\$env:USERNAME")

$ErrorActionPreference = 'Stop'
$Dir = $PSScriptRoot
Start-Transcript -Path (Join-Path $Dir 'install.log') -Force | Out-Null
$Script = Join-Path $Dir 'vm_watchdog.ps1'
$Config = Join-Path $Dir 'config.json'

if (-not (Test-Path $Config)) {
    Copy-Item (Join-Path $Dir 'config.example.json') $Config
    Write-Host "config.json criado a partir do exemplo - revise vm_name/vm_ip antes de seguir." -ForegroundColor Yellow
}

$VBox = Join-Path $env:ProgramFiles 'Oracle\VirtualBox\VBoxManage.exe'
if (Test-Path $VBox) {
    Write-Host "VMs encontradas para este usuario:"
    & $VBox list vms
} else {
    Write-Host "ATENCAO: VBoxManage nao encontrado em $VBox - ajuste vboxmanage_path no config.json" -ForegroundColor Red
}

# Fonte do Visualizador de Eventos (os alertas ficam registrados la mesmo com a VM fora)
try { New-EventLog -LogName Application -Source 'OminiVmWatchdog' -ErrorAction Stop } catch {}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Script`"" `
    -WorkingDirectory $Dir
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$boot = New-ScheduledTaskTrigger -AtStartup
$boot.Delay = 'PT1M'
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
# S4U = roda mesmo sem ninguem logado, com o usuario atual, sem guardar senha
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType S4U -RunLevel Highest

Register-ScheduledTask -TaskName 'OminiChannel - Vigia da VM' -Action $action -Trigger @($every, $boot) `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Tarefa 'OminiChannel - Vigia da VM' instalada (a cada 1 min + na inicializacao)." -ForegroundColor Green
Write-Host "Conta: $User"
Stop-Transcript | Out-Null
