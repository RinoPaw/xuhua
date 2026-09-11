@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PROJECT_DIR=%~dp0"
for %%I in ("%PROJECT_DIR%..") do set "PACKAGE_DIR=%%~fI"
set "PYTHON=%PACKAGE_DIR%\.venv\Scripts\python.exe"
set "UV_LINK_MODE=copy"
set "UV_PROJECT_ENVIRONMENT=%PACKAGE_DIR%\.venv"

if not exist ".env" (
    echo [ERROR] .env was not found.
    echo Copy .env.example to .env and fill in the required values.
    pause
    exit /b 1
)

set "HOST="
set "PORT="
for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"HOST=" /C:"PORT=" ".env"') do set "%%A=%%B"
if not defined HOST (
    echo [ERROR] HOST is missing from .env.
    pause
    exit /b 1
)
if not defined PORT (
    echo [ERROR] PORT is missing from .env.
    pause
    exit /b 1
)
set "LOCAL_URL=http://%HOST%:%PORT%"

set "UV_EXE=%PACKAGE_DIR%\runtime\uv\uv.exe"
if not exist "%UV_EXE%" (
    set "UV_EXE="
    for /f "delims=" %%I in ('where uv 2^>nul') do if not defined UV_EXE set "UV_EXE=%%I"
)

if not defined UV_EXE (
    echo [ERROR] uv was not found.
    echo Put uv at Packages\runtime\uv\uv.exe or install it on PATH.
    pause
    exit /b 1
)

if not exist "%PYTHON%" (
    echo [SETUP] Creating shared Packages Python runtime...
    "%UV_EXE%" venv --python 3.12 "%PACKAGE_DIR%\.venv"
    if errorlevel 1 (
        echo [ERROR] Failed to create the shared Python runtime.
        pause
        exit /b 1
    )
)

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm was not found on PATH. Install Node.js and try again.
    pause
    exit /b 1
)

powershell.exe -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 (
    echo [ERROR] Port %PORT% is already in use. Close the existing service and try again.
    pause
    exit /b 2
)

echo [SETUP] Building the web interface...
pushd "%PROJECT_DIR%frontend"
call npm ci --prefer-offline --no-audit --no-fund
if errorlevel 1 (
    popd
    echo [ERROR] Frontend dependency installation failed.
    pause
    exit /b 1
)
call npm run build
if errorlevel 1 (
    popd
    echo [ERROR] Frontend build failed.
    pause
    exit /b 1
)
popd

echo [CHECK] Checking Xuhua Python dependencies...
call :check_dependencies
if errorlevel 1 (
    echo [SETUP] Installing Xuhua dependencies into the shared runtime...
    "%UV_EXE%" pip install --python "%PYTHON%" --requirements "%PROJECT_DIR%pyproject.toml"
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        pause
        exit /b 1
    )

    call :check_dependencies
    if errorlevel 1 (
        echo [ERROR] Some Xuhua dependencies are still missing.
        pause
        exit /b 1
    )
)

if /I "%~1"=="--check" (
    echo [OK] The runtime environment is ready.
    exit /b 0
)

echo Starting Xuhua at %LOCAL_URL%...
echo Close this window to stop the service.
start "" /b powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%PROJECT_DIR%scripts\open_browser_when_ready.ps1" -Url "%LOCAL_URL%"
"%UV_EXE%" run --no-sync --python "%PYTHON%" --env-file ".env" python "app.py"

set "XUHUA_EXIT_CODE=%ERRORLEVEL%"

if not "%XUHUA_EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Xuhua stopped unexpectedly. Exit code: %XUHUA_EXIT_CODE%
    pause
    exit /b %XUHUA_EXIT_CODE%
)

exit /b 0

:check_dependencies
"%PYTHON%" -c "import edge_tts, fastapi, httpx, pypinyin, uvicorn, websockets" >nul 2>nul
exit /b %ERRORLEVEL%
