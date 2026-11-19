# Authenticode-sign files when a certificate is configured (GitHub secrets), otherwise do nothing.
#   WINDOWS_CERT_PFX_BASE64   base64 of your .pfx code-signing certificate
#   WINDOWS_CERT_PASSWORD     its password
# Usage: pwsh packaging/sign.ps1 dist\VaultMove\VaultMove.exe dist\VaultMove-Portable-1.0.0.exe
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Files)

if (-not $env:WINDOWS_CERT_PFX_BASE64) {
    Write-Host "No signing certificate configured: skipping code signing (see README, 'SmartScreen')."
    exit 0
}
$pfx = Join-Path $env:RUNNER_TEMP "codesign.pfx"
[IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:WINDOWS_CERT_PFX_BASE64))
$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe |
    Where-Object { $_.FullName -match "\\x64\\" } | Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) { throw "signtool.exe not found" }
try {
    foreach ($f in $Files) {
        & $signtool.FullName sign /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com `
            /f $pfx /p $env:WINDOWS_CERT_PASSWORD /d "VaultMove" $f
        if ($LASTEXITCODE -ne 0) { throw "signing failed for $f" }
    }
} finally {
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
}
