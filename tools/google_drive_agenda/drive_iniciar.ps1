# Abre o Google Drive para computador no SRV-SERVWELD (agendado às 20:30, depois do backup do
# Softsystem das 20:00) - ele sobe para a nuvem tudo o que mudou no dia. Pedido de 15/10/2026.
$log = "C:\OminiVmWatchdog\google_drive_agenda.log"
if (Get-Process -Name GoogleDriveFS -ErrorAction SilentlyContinue) {
    Add-Content $log "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Google Drive já estava aberto"
    exit 0
}
$exe = Get-ChildItem "C:\Program Files\Google\Drive File Stream\*\GoogleDriveFS.exe" -ErrorAction SilentlyContinue |
       Sort-Object { [version]($_.Directory.Name -replace '[^0-9.]', '') } -Descending | Select-Object -First 1
if (-not $exe) {
    Add-Content $log "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ERRO: GoogleDriveFS.exe não encontrado"
    exit 1
}
Start-Process -FilePath $exe.FullName
Add-Content $log "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Google Drive aberto ($($exe.FullName))"
