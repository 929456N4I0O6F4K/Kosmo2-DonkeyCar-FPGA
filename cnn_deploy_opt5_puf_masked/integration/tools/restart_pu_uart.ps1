#Requires -RunAsAdministrator
# Restart only the Kosmo PU CP210x device. Does not send UART data.
$ErrorActionPreference = 'Stop'
$uartInstanceId = 'USB\VID_10C4&PID_EA60\0001'
$projectRoot = Split-Path -Parent $PSScriptRoot
$reportDirectory = Join-Path $projectRoot ('runs\' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '_uart_restart')
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
$reportFile = Join-Path $reportDirectory 'restart.log'
Start-Transcript -Path $reportFile | Out-Null
try {
    Get-PnpDevice -InstanceId $uartInstanceId -PresentOnly -ErrorAction Stop |
        Format-List Status, FriendlyName, InstanceId | Out-Host
    & "$env:SystemRoot\System32\pnputil.exe" /restart-device $uartInstanceId
    $restartExitCode = $LASTEXITCODE
    Write-Output "PnPUtil exit code: $restartExitCode"
    # A zero PnPUtil exit code alone does not prove that the port can open.
    Get-PnpDevice -InstanceId $uartInstanceId -ErrorAction Stop |
        Format-List Status, FriendlyName, InstanceId | Out-Host
    Write-Output 'Re-test the COM port after this script exits.'
    if ($restartExitCode -ne 0) {
        throw "PnPUtil returned $restartExitCode; inspect the restart output."
    }
} finally {
    Stop-Transcript | Out-Null
}
