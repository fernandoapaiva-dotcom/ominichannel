@echo off
setlocal enabledelayedexpansion

echo ============================================
echo  Instalador do Vigia de Banco - Ominichannel
echo ============================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if not exist "config.json" (
    echo [ERRO] config.json nao encontrado nesta pasta.
    echo Copie config.example.json para config.json e preencha com a chave de API,
    echo o usuario/senha do Firebird e os caminhos antes de instalar.
    pause
    exit /b 1
)

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [AVISO] Esta janela nao esta rodando como Administrador.
    echo Para funcionar automaticamente para TODOS os operadores desta estacao,
    echo feche esta janela, clique com o botao direito em install.bat e escolha
    echo "Executar como administrador", depois rode de novo.
    echo.
    echo Continuando mesmo assim - vai instalar so para o usuario atual: %USERNAME%
    echo.
    set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
) else (
    echo Rodando como Administrador - instalando para TODOS os operadores desta estacao.
    echo.
    set "STARTUP_DIR=C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp"
)

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python nao encontrado nesta estacao. Baixando e instalando automaticamente...
    set "PY_INSTALLER=%TEMP%\python_installer.exe"
    powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '%PY_INSTALLER%'"
    if not exist "%PY_INSTALLER%" (
        echo [ERRO] Falha ao baixar o instalador do Python. Verifique a internet desta estacao.
        pause
        exit /b 1
    )
    echo Instalando Python silenciosamente ^(pode levar 1-2 minutos^)...
    "%PY_INSTALLER%" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
    del "%PY_INSTALLER%" >nul 2>&1
    set "PATH=%PATH%;C:\Program Files\Python312\;C:\Program Files\Python312\Scripts\"
    where python >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERRO] Python foi instalado mas nao foi encontrado nesta janela.
        echo Feche este instalador, abra um NOVO Prompt de Comando e rode install.bat de novo.
        pause
        exit /b 1
    )
)
echo Python encontrado:
python --version
echo.

if not exist "venv" (
    echo Criando ambiente Python isolado...
    python -m venv venv
)

echo Instalando dependencias...
"venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
"venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [ERRO] Falha ao instalar as dependencias.
    pause
    exit /b 1
)
echo.

echo Criando o iniciador automatico...
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WshShell.CurrentDirectory = "%SCRIPT_DIR%"
echo WshShell.Run """%SCRIPT_DIR%venv\Scripts\pythonw.exe"" ""%SCRIPT_DIR%db_watcher.py""", 0, False
) > "%SCRIPT_DIR%run_db_watcher.vbs"

copy /Y "%SCRIPT_DIR%run_db_watcher.vbs" "%STARTUP_DIR%\OminichannelDbWatcher.vbs" >nul
if %errorlevel% neq 0 (
    echo [ERRO] Nao foi possivel copiar para a pasta de Inicializacao: %STARTUP_DIR%
    pause
    exit /b 1
)
echo Instalado em: %STARTUP_DIR%\OminichannelDbWatcher.vbs
echo.

echo Iniciando o vigia agora para teste...
wscript.exe "%SCRIPT_DIR%run_db_watcher.vbs"
timeout /t 3 >nul

echo.
echo ============================================
echo  Instalacao concluida!
echo ============================================
echo O vigia de banco vai iniciar sozinho sempre que alguem fizer login
echo nesta estacao. Confira o arquivo db_watcher.log nesta pasta para ver
echo se esta funcionando.
echo.
pause
