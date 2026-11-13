param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    foreach ($project in @('Adws.Windows.Host', 'Adws.Windows.Wm')) {
        dotnet publish $project -c Release -r win-x64 --self-contained false -o artifacts/win-x64
        if ($LASTEXITCODE -ne 0) { throw "Publish failed: $project" }
    }
    if (-not $SkipTests) {
        dotnet run --project Adws.Windows.Tests -c Release -- --wm (Resolve-Path artifacts/win-x64/Adws.Windows.Wm.dll)
        if ($LASTEXITCODE -ne 0) { throw 'Windows core/protocol tests failed' }
    }
    Copy-Item windows-config.example.json artifacts/win-x64/windows-config.example.json
} finally { Pop-Location }
