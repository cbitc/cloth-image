# 启动开发环境：后端（:8000，热重载）+ 前端（:3000）
. (Join-Path $PSScriptRoot "common.ps1")

if (-not (Test-Path $PythonExe)) {
    throw "未找到 backend/.venv，请先运行 .\scripts\setup.ps1"
}

# 各开一个命令行窗口，便于分别查看日志
Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/k", "`"$PythonExe`" -m uvicorn app.main:app --reload --port 8000" `
    -WorkingDirectory $BackendDir

Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/k", "npm run dev" `
    -WorkingDirectory $FrontendDir

Write-Host "后端 http://localhost:8000/docs ；前端 http://localhost:3000"
