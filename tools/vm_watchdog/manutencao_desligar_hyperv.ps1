# Manutencao do SRV-SERVWELD (12/10/2026): tira o VirtualBox do modo lento sobre o Hyper-V.
#
# Por que: o VirtualBox nao consegue usar o AMD-V do processador (AMD FX-6300) enquanto o Hyper-V
# esta ligado - cai no modo NEM ("AMD-V is not available -> fall back to NEM" no VBox.log), e a
# VM do OminiChannel teve 400+ soft lockups por boot e travou varias vezes. Nao existe nenhuma VM
# no Hyper-V; ele so esta ligado por causa do switch virtual "ExternalSwitch", por onde passa a
# rede do PROPRIO servidor (IP 192.168.15.16 esta no "vEthernet (ExternalSwitch)").
#
# O que faz (com log em C:\OminiVmWatchdog\manutencao.log):
#   1. Pausa o vigia da VM (senao ele religa a VM no meio da manutencao)
#   2. Desliga as 2 VMs com calma (ACPI; forca so se nao desligarem em 3 min)
#   3. "Windows Server - Centro Oeste" passa de 3 CPUs para 1
#   4. Placa de rede das 2 VMs: do adaptador do Hyper-V para a placa fisica Realtek
#   5. Remove o ExternalSwitch - a rede do servidor volta direto pra Realtek (mesmo MAC, entao o
#      roteador devolve o mesmo IP .16; se nao devolver, fixa .16 na mao). A RDP pode cair por
#      alguns segundos aqui - o script continua rodando sozinho.
#   6. Desliga o Hyper-V na inicializacao (bcdedit hypervisorlaunchtype off)
#   7. Reativa o vigia e pede confirmacao pra REINICIAR o servidor
# Depois do reinicio o vigia liga a VM do OminiChannel sozinho. A Centro Oeste (Guardiao) liga
# como hoje (manual), ou por este mesmo script se ela tiver sido desligada aqui (passo 8).
#
# Rodar NO SRV-SERVWELD, PowerShell como Administrador, logado como SERVWELD\Administrator,
# FORA do horario de uso (Softsystem, arquivos e as VMs ficam fora uns 10 minutos):
#   powershell -ExecutionPolicy Bypass -File C:\OminiVmWatchdog\manutencao_desligar_hyperv.ps1
#
# Para DESFAZER (volta tudo como era):
#   bcdedit /set hypervisorlaunchtype auto ; Restart-Computer
#   (depois) New-VMSwitch -Name ExternalSwitch -NetAdapterName Ethernet -AllowManagementOS $true
#   e voltar o bridge das VMs pra "Hyper-V Virtual Ethernet Adapter"

$ErrorActionPreference = 'Stop'
Start-Transcript -Path 'C:\OminiVmWatchdog\manutencao.log' -Append | Out-Null
$VBox = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
$Task = 'OminiChannel - Vigia da VM'
$Omini = 'OminiChannel-Ubuntu-VBox'
$Centro = 'Windows Server - Centro Oeste'
$Nic = 'Realtek PCIe GBE Family Controller'
$ServerIp = '192.168.15.16'

function Step($t) { Write-Host "`n== $t ==" -ForegroundColor Cyan }
function VmState($vm) { ((& $VBox showvminfo $vm --machinereadable) | Where-Object { $_ -match '^VMState=' }) -replace '^VMState="?([^"]*)"?$', '$1' }

Write-Host "Isto vai desligar as VMs, mexer na rede do servidor e REINICIAR o SRV-SERVWELD." -ForegroundColor Yellow
if ((Read-Host "Digite SIM para continuar") -ne 'SIM') { Write-Host 'Cancelado.'; Stop-Transcript | Out-Null; exit }

Step '1. Pausando o vigia da VM'
Disable-ScheduledTask -TaskName $Task | Out-Null

Step '2. Desligando as VMs'
$centroWasRunning = (VmState $Centro) -eq 'running'
foreach ($vm in @($Omini, $Centro)) {
    if ((VmState $vm) -ne 'running') { Write-Host "$vm ja esta '$(VmState $vm)'"; continue }
    Write-Host "Desligando $vm (ACPI)..."
    & $VBox controlvm $vm acpipowerbutton
    $deadline = (Get-Date).AddMinutes(3)
    while ((VmState $vm) -eq 'running' -and (Get-Date) -lt $deadline) { Start-Sleep 5 }
    if ((VmState $vm) -eq 'running') { Write-Host "Nao desligou em 3 min - forcando"; & $VBox controlvm $vm poweroff }
    Start-Sleep 5
    Write-Host "$vm -> $(VmState $vm)"
}

Step '3. Centro Oeste com 1 CPU'
& $VBox modifyvm $Centro --cpus 1
Write-Host ((& $VBox showvminfo $Centro --machinereadable) | Where-Object { $_ -match '^cpus=' })

Step '4. Rede das VMs na placa fisica'
foreach ($vm in @($Omini, $Centro)) {
    $nic1 = ((& $VBox showvminfo $vm --machinereadable) | Where-Object { $_ -match '^nic1=' }) -replace '^nic1="?([^"]*)"?$', '$1'
    if ($nic1 -eq 'bridged') { & $VBox modifyvm $vm --bridgeadapter1 $Nic; Write-Host "$vm -> bridge em '$Nic'" }
    else { Write-Host "$vm usa '$nic1' (nao e bridge) - sem mudanca" }
}

Step '5. Removendo o ExternalSwitch (a rede pisca aqui)'
Remove-VMSwitch -Name 'ExternalSwitch' -Force
$ok = $false
for ($i = 0; $i -lt 24; $i++) {
    Start-Sleep 5
    $ip = (Get-NetIPAddress -InterfaceAlias 'Ethernet' -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress
    if ($ip -eq $ServerIp) { $ok = $true; break }
}
if (-not $ok) {
    Write-Host "Roteador nao devolveu $ServerIp (veio '$ip') - fixando $ServerIp na placa Ethernet" -ForegroundColor Yellow
    Get-NetIPAddress -InterfaceAlias 'Ethernet' -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false
    New-NetIPAddress -InterfaceAlias 'Ethernet' -IPAddress $ServerIp -PrefixLength 24 -DefaultGateway '192.168.15.1' | Out-Null
    Set-DnsClientServerAddress -InterfaceAlias 'Ethernet' -ServerAddresses '192.168.15.1'
}
Get-NetIPAddress -InterfaceAlias 'Ethernet' -AddressFamily IPv4 | Format-Table InterfaceAlias, IPAddress, PrefixOrigin -AutoSize
if (Test-Connection 192.168.15.1 -Count 2 -Quiet) { Write-Host 'Rede OK (roteador responde)' -ForegroundColor Green }
else { Write-Host 'ATENCAO: roteador nao responde - NAO reinicie, veja a rede antes' -ForegroundColor Red; Stop-Transcript | Out-Null; exit 1 }

Step '6. Desligando o Hyper-V na inicializacao'
bcdedit /set hypervisorlaunchtype off
bcdedit /enum '{current}' | Select-String hypervisorlaunchtype

Step '7. Reativando o vigia'
Enable-ScheduledTask -TaskName $Task | Out-Null

# 8. Se a Centro Oeste estava ligada, cria tarefa que liga ela a cada inicializacao do servidor
if ($centroWasRunning) {
    $a = New-ScheduledTaskAction -Execute $VBox -Argument "startvm `"$Centro`" --type headless"
    $t = New-ScheduledTaskTrigger -AtStartup; $t.Delay = 'PT2M'
    $p = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest
    Register-ScheduledTask -TaskName 'OminiChannel - Ligar Centro Oeste' -Action $a -Trigger $t -Principal $p -Force | Out-Null
    Write-Host "Centro Oeste passa a ligar sozinha 2 min depois de cada inicializacao (tarefa 'OminiChannel - Ligar Centro Oeste')"
}

Write-Host "`nTudo pronto. Falta so REINICIAR o servidor pra o Hyper-V sair de cena." -ForegroundColor Green
$r = Read-Host 'Digite SIM para reiniciar agora'
Stop-Transcript | Out-Null
if ($r -eq 'SIM') { Restart-Computer -Force } else { Write-Host 'Reinicie quando puder (Restart-Computer).' }
