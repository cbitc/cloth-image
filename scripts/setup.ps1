# 安装依赖并准备本地开发环境（无需 Docker）
. (Join-Path $PSScriptRoot "common.ps1")

# 1) .env（首次自动从 .env.example 生成）
$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $Root ".env.example") $envFile
    Write-Host "[ok] 已生成 .env"
}

# 2) 后端：venv + 依赖（SQLite 表在首次启动后端时自动创建）
if (-not (Test-Path $PythonExe)) {
    Invoke-Step "python" @("-m", "venv", ".venv") $BackendDir
    Write-Host "[ok] 已创建 backend/.venv"
}
Invoke-Step $PythonExe @("-m", "pip", "install", "--upgrade", "pip") $BackendDir
Invoke-Step $PythonExe @("-m", "pip", "install", "-e", ".[dev]") $BackendDir

# 3) 前端：npm 依赖
Invoke-Step "npm" @("install") $FrontendDir

Write-Host "[done] 运行 .\scripts\dev.ps1 启动开发环境"
