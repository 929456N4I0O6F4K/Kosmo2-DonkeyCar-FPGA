param(
    [string]$BoardAddress = '',
    [switch]$NoProgram,
    [ValidateRange(2, 1000)][int]$Frames = 50,
    [switch]$NoBrowser,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
Push-Location "$PSScriptRoot/integration/training"
try {
    $deployArgs = @('tools/deploy_board.py', '--frames', "$Frames")
    if ($BoardAddress) { $deployArgs += @('--host', $BoardAddress) }
    if ($NoProgram) { $deployArgs += '--no-program' }
    if ($CheckOnly) { $deployArgs += '--check-only' }
    & python @deployArgs
    if ($LASTEXITCODE -ne 0) { throw 'CNN deployment failed; inspect integration/training/runs' }
    if (-not $CheckOnly -and -not $NoBrowser) {
        $effectiveAddress = $BoardAddress
        if (-not $effectiveAddress) { $effectiveAddress = $env:KOSMO_BOARD_HOST }
        if (-not $effectiveAddress) {
            $connectionFile = "$PSScriptRoot/../training/board_connection.json"
            if (-not (Test-Path -LiteralPath $connectionFile)) {
                $connectionFile = "$PSScriptRoot/integration/training/board_connection.json"
            }
            $effectiveAddress = (Get-Content -LiteralPath $connectionFile -Raw -Encoding UTF8 | ConvertFrom-Json).host
        }
        Start-Process -FilePath "http://${effectiveAddress}:8080/"
    }
} finally { Pop-Location }
