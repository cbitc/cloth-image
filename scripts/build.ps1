# 构建：前端生产产物 + 后端字节码预编译 + 类型检查
. (Join-Path $PSScriptRoot "common.ps1")

if (-not $env:NEXT_PUBLIC_API_BASE_URL) {
    $env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000"
}

if (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue) {
    Write-Warning "3000 端口被占用（可能正在跑 npm run dev）。dev 会覆盖 .next，建议先停掉再构建。"
}

Invoke-Step "npm" @("run", "build") $FrontendDir
Invoke-Step "npx" @("tsc", "--noEmit") $FrontendDir
Invoke-Step $PythonExe @("-m", "compileall", "-q", "app") $BackendDir

Write-Host "[done] 生产启动请用 .\scripts\start.ps1"
