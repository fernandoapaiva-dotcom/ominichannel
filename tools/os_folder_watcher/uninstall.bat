@echo off
echo Removendo o Vigia de Pasta desta estacao...

powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*watcher.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

if exist "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp\OminichannelWatcher.vbs" (
    del "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp\OminichannelWatcher.vbs"
    echo Removido de: todos os operadores desta estacao.
)

if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\OminichannelWatcher.vbs" (
    del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\OminichannelWatcher.vbs"
    echo Removido de: usuario atual (%USERNAME%).
)

echo.
echo O vigia nao vai mais iniciar sozinho. Se quiser reinstalar depois, rode install.bat novamente.
echo (O ambiente Python instalado - pasta "venv" - foi mantido e nao precisa ser reinstalado.)
pause
