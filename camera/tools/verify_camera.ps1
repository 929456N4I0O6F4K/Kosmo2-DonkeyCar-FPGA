param(
    [switch]$Build,
    [switch]$SkipProgram,
    [int]$NormalCount=10,
    [int]$ResetCount=3,
    [int]$SoakSeconds=600
)
$ErrorActionPreference='Stop'
$cameraRoot=Split-Path -Parent $PSScriptRoot
$pdsBin='C:/pango/PDS_2025.2-ads/bin'
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
if ($NormalCount -lt 2 -or $ResetCount -lt 1 -or $SoakSeconds -lt 5) {
    throw 'Use at least two normal frames, one reset and five monitoring seconds.'
}
Push-Location $cameraRoot
try {
    if ($Build) {
        python -X utf8 tools/update_jtag_project.py
        if ($LASTEXITCODE -ne 0) { throw 'Project update failed.' }
        $buildLog=Join-Path $cameraRoot "build/verify_${stamp}_build.log"
        Write-Host "Building JTAG firmware. Log: $buildLog"
        & "$pdsBin/pds_shell.exe" -work_dir "$cameraRoot/build/pds_jtag" -file "$cameraRoot/scripts/build_jtag.tcl" *> $buildLog
        if ($LASTEXITCODE -ne 0) { throw "PDS build failed: $buildLog" }
    }
    python -X utf8 tools/check_build.py --jtag
    if ($LASTEXITCODE -ne 0) { throw 'Implementation checks failed; rebuild the current sources.' }
    if (!$SkipProgram) {
        $programLog=Join-Path $cameraRoot "build/verify_${stamp}_program.log"
        Write-Host "Loading PA firmware through JTAG. Log: $programLog"
        & "$pdsBin/cdt_cfg_shell.exe" -file "$cameraRoot/scripts/program_jtag.tcl" *> $programLog
        if ($LASTEXITCODE -ne 0) { throw "PA programming failed: $programLog" }
    }
    python -X utf8 tools/accept_camera.py --normal-count $NormalCount --reset-count $ResetCount --soak-seconds $SoakSeconds
    if ($LASTEXITCODE -ne 0) { throw 'Camera acceptance failed; inspect the saved run.' }
} finally {
    Pop-Location
}
