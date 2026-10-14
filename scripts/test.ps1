# 测试：后端 pytest + 前端类型检查
. (Join-Path $PSScriptRoot "common.ps1")

Invoke-Step $PythonExe @("-m", "pytest", "-q") $BackendDir
Invoke-Step "npx" @("tsc", "--noEmit") $FrontendDir

Write-Host "[ok] 测试通过"
