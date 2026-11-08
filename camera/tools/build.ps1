param([string]$PdsRoot='C:/pango/PDS_2025.2-ads')
$ErrorActionPreference='Stop'
$cameraRoot=Split-Path -Parent $PSScriptRoot
$pdsShell=Join-Path $PdsRoot 'bin/pds_shell.exe'
if (!(Test-Path -LiteralPath $pdsShell)) { throw "PDS shell not found: $pdsShell" }
Push-Location $cameraRoot
try {
    python -X utf8 tools/generate_init.py
    if ($LASTEXITCODE -ne 0) { throw 'ROM generation failed' }
    python -X utf8 tools/update_project.py
    if ($LASTEXITCODE -ne 0) { throw 'PDS update failed' }
    & $pdsShell -work_dir (Join-Path $cameraRoot 'build/pds') -file (Join-Path $cameraRoot 'scripts/build.tcl')
    if ($LASTEXITCODE -ne 0) { throw 'PDS build failed; inspect build/pds reports' }
    python -X utf8 tools/check_build.py
    if ($LASTEXITCODE -ne 0) { throw 'Implementation verification failed' }
} finally { Pop-Location }
