@echo off
REM Cria as duas tarefas no Agendador do Windows do SRV-SERVWELD (rodar como Administrador).
REM Os scripts precisam estar em C:\OminiVmWatchdog (mesma pasta do vigia da VM).
schtasks /Create /F /TN "OminiChannel\Fechar Google Drive" /SC DAILY /ST 07:30 /RU Administrator /IT ^
  /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\OminiVmWatchdog\drive_parar.ps1"
schtasks /Create /F /TN "OminiChannel\Abrir Google Drive" /SC DAILY /ST 20:30 /RU Administrator /IT ^
  /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\OminiVmWatchdog\drive_iniciar.ps1"
echo.
echo Tarefas criadas. Conferir em: Agendador de Tarefas ^> Biblioteca ^> OminiChannel
pause
