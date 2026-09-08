@echo off
setlocal
chcp 65001 >nul
set "INSTALLER=%TEMP%\xuhua-install-lab.ps1"
if /I "%~1"=="--syntax-check" goto :syntax_ok
echo [1/2] 正在从 GitHub 获取叙华安装器...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest 'https://raw.githubusercontent.com/RinoPaw/xuhua/main/deploy/install-lab.ps1' -OutFile '%INSTALLER%' -UseBasicParsing"
if errorlevel 1 goto :fail
echo [2/2] 正在安装源码、模型和依赖...
if exist "%~dp0xuhua.env" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%INSTALLER%" -EnvFile "%~dp0xuhua.env"
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%INSTALLER%"
)
if errorlevel 1 goto :fail
exit /b 0
:syntax_ok
echo [OK] bootstrap syntax
exit /b 0
:fail
echo.
echo [ERROR] 安装失败，请保留本窗口中的错误信息。
pause
exit /b 1
