param(
    [switch]$NoProgram,
    [switch]$SoftwareOnly,
    [switch]$CheckOnly,
    [string]$BoardHost = '',
    [ValidateRange(2, 1000)][int]$Frames = 100
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Push-Location $PSScriptRoot
try {
    $python = (Get-Command python -ErrorAction Stop).Source
    $deployArgs = @('tools/deploy_board.py', '--frames', "$Frames")
    if ($BoardHost) { $deployArgs += @('--host', $BoardHost) }
    if ($NoProgram) { $deployArgs += '--no-program' }
    if ($SoftwareOnly) { $deployArgs += '--software-only' }
    if ($CheckOnly) { $deployArgs += '--check-only' }
    & $python @deployArgs
    if ($LASTEXITCODE -ne 0) { throw 'Deployment stopped. See the log path and error above.' }
} finally {
    Pop-Location
}
