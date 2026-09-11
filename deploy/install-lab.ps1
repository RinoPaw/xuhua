[CmdletBinding()]
param(
    [string]$InstallRoot = "D:\Projects\Packages",
    [string]$Repository = "https://github.com/RinoPaw/xuhua.git",
    [string]$Branch = "main",
    [string]$EnvFile = "",
    [switch]$SkipLaunch
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

function Step([string]$Text) { Write-Host "`n=== $Text ===" -ForegroundColor Cyan }
function Require-Command([string]$Name, [string]$WingetId) {
    if (Get-Command $Name -ErrorAction SilentlyContinue) { return }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "缺少 $Name，且本机没有 winget。请先安装 $Name 后重试。"
    }
    Step "安装 $Name"
    winget install --id $WingetId -e --accept-package-agreements --accept-source-agreements
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { throw "$Name 安装后仍不在 PATH。请重开终端再运行。" }
}

function Get-Uv([string]$Root) {
    $bundled = Join-Path $Root "runtime\uv\uv.exe"
    if (Test-Path -LiteralPath $bundled) { return $bundled }
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    Step "安装 uv"
    $installer = Join-Path $env:TEMP "uv-install.ps1"
    Invoke-WebRequest "https://astral.sh/uv/install.ps1" -OutFile $installer -UseBasicParsing
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer
    $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (-not (Test-Path -LiteralPath $uv)) { throw "uv 安装失败。" }
    return $uv
}

Step "检查基础工具"
Require-Command "git" "Git.Git"
Require-Command "node" "OpenJS.NodeJS.LTS"
Require-Command "npm" "OpenJS.NodeJS.LTS"

$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$Project = Join-Path $InstallRoot "叙华"
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

Step "同步 GitHub 源码"
if (Test-Path -LiteralPath (Join-Path $Project ".git")) {
    git -C $Project fetch origin $Branch --prune
    git -C $Project checkout $Branch
    git -C $Project pull --ff-only origin $Branch
} elseif (Test-Path -LiteralPath $Project) {
    throw "目标目录已存在但不是 Git 仓库：$Project"
} else {
    git clone --branch $Branch --single-branch $Repository $Project
}
if ($LASTEXITCODE -ne 0) { throw "GitHub 源码同步失败。" }

$Uv = Get-Uv $InstallRoot

if (-not $EnvFile) {
    $beside = Join-Path (Split-Path -Parent $PSCommandPath) "xuhua.env"
    if (Test-Path -LiteralPath $beside) { $EnvFile = $beside }
}
if ($EnvFile) {
    $resolvedEnv = (Resolve-Path -LiteralPath $EnvFile).Path
    Copy-Item -LiteralPath $resolvedEnv -Destination (Join-Path $Project ".env") -Force
} elseif (-not (Test-Path -LiteralPath (Join-Path $Project ".env"))) {
    Copy-Item -LiteralPath (Join-Path $Project ".env.example") -Destination (Join-Path $Project ".env")
    Write-Warning "已生成 .env；如需 AI 与实时语音，请填入对应密钥。"
}

Step "安装依赖并构建"
& (Join-Path $Project "start.bat") --check
if ($LASTEXITCODE -ne 0) { throw "叙华运行环境检查失败。" }

Step "安装完成"
Write-Host "源码：$Project"
Write-Host "启动：$(Join-Path $Project 'start.bat')"
if (-not $SkipLaunch) { & (Join-Path $Project "start.bat") }
