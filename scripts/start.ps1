# 生产启动（需先执行 .\scripts\build.ps1）
. (Join-Path $PSScriptRoot "common.ps1")

if (-not (Test-Path $PythonExe)) {
    throw "未找到 backend/.venv，请先运行 .\scripts\setup.ps1"
}
if (-not (Test-Path (Join-Path $FrontendDir ".next\BUILD_ID"))) {
    throw "未找到前端生产构建（frontend/.next/BUILD_ID）。请先运行 .\scripts\build.ps1（注意：npm run dev 会覆盖 .next，构建前先停掉 dev）"
}

Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/k", "`"$PythonExe`" -m uvicorn app.main:app --host 0.0.0.0 --port 8000" `
    -WorkingDirectory $BackendDir

Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/k", "npm run start" `
    -WorkingDirectory $FrontendDir

Write-Host "后端 http://localhost:8000 ；前端 http://localhost:3010"
