param([string]$Go = "$PSScriptRoot/build/toolchain/go/bin/go.exe")
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Go)) { throw 'Install Go or pass -Go <path to go.exe>' }
$oldBuildEnv = @{}
foreach ($name in @('GOCACHE','GOMODCACHE','GOTOOLCHAIN','CGO_ENABLED','GOOS','GOARCH')) {
    $oldBuildEnv[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
Push-Location $PSScriptRoot
try {
    $env:GOCACHE = "$PSScriptRoot/build/go-cache"
    $env:GOMODCACHE = "$PSScriptRoot/build/go-mod-cache"
    $env:GOTOOLCHAIN = 'local'
    $env:CGO_ENABLED = '0'
    $env:GOOS = 'windows'
    $env:GOARCH = 'amd64'
    & $Go test . -count=1
    if ($LASTEXITCODE -ne 0) { throw 'Go tests failed' }
    & $Go vet .
    if ($LASTEXITCODE -ne 0) { throw 'Go vet failed' }
    New-Item -ItemType Directory -Force bin | Out-Null
    & $Go build -trimpath -o bin/kosmo-collect.exe .
    if ($LASTEXITCODE -ne 0) { throw 'Windows build failed' }
    $env:GOOS = 'linux'
    $env:GOARCH = 'arm64'
    & $Go vet .
    if ($LASTEXITCODE -ne 0) { throw 'Linux vet failed' }
    & $Go build -trimpath -ldflags '-s -w' -o bin/kosmo-collect-linux-arm64 .
    if ($LASTEXITCODE -ne 0) { throw 'ARM64 build failed' }
    Get-FileHash bin/kosmo-collect* | Format-Table
} finally {
    foreach ($name in $oldBuildEnv.Keys) {
        [Environment]::SetEnvironmentVariable($name, $oldBuildEnv[$name], 'Process')
    }
    Pop-Location
}
