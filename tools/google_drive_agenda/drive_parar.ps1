# Fecha o Google Drive para computador no SRV-SERVWELD (agendado às 07:30) - pedido de 15/10/2026.
# Durante o expediente a sincronização fica parada: o Drive "segurando" os arquivos de
# C:\Users\Administrator\My Drive (o Z: da loja) fazia a pasta de rede engasgar e travar a VM do
# OminiChannel. Os arquivos continuam no disco do servidor - a loja e o sistema usam normalmente.
$log = "C:\OminiVmWatchdog\google_drive_agenda.log"
$procs = Get-Process -Name GoogleDriveFS -ErrorAction SilentlyContinue
if ($procs) {
    $procs | Stop-Process -Force
    Add-Content $log "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Google Drive fechado ($($procs.Count) processo(s))"
} else {
    Add-Content $log "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Google Drive já estava fechado"
}
