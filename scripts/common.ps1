# 脚本公共部分（被各脚本 dot-source，勿直接运行）
$ErrorActionPreference = "Continue"

$Root = Split-Path $PSScriptRoot -Parent
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"

# 运行外部命令并按退出码判定成败（避免 PowerShell 5.1 把 stderr 日志当错误）
function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory
    )
    $entered = $false
    if ($WorkingDirectory) { Push-Location $WorkingDirectory; $entered = $true }
    try { & $FilePath @Arguments; $code = $LASTEXITCODE }
    finally { if ($entered) { Pop-Location } }
    if ($code -ne 0) {
        throw "命令失败（exit $code）：$FilePath $($Arguments -join ' ')"
    }
}
