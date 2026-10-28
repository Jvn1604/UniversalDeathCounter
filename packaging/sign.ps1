# Signs files with an Authenticode code-signing certificate (.pfx).
#
# Used by CI when the SIGNING_CERT_PFX_BASE64 / SIGNING_CERT_PASSWORD
# repository secrets are set; see docs/code-signing.md. Signed builds stop
# SmartScreen's "Unknown publisher" warning and lower antivirus false
# positives. Without the secrets, CI skips signing and builds as before.
#
# Usage: ./packaging/sign.ps1 <file> [<file> ...]

param([Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)][string[]]$Files)

$ErrorActionPreference = "Stop"

if (-not $env:SIGNING_CERT_PFX_BASE64) { throw "SIGNING_CERT_PFX_BASE64 is not set." }

$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) { throw "signtool.exe not found (Windows SDK missing)." }

$pfx = Join-Path $env:RUNNER_TEMP "signing-cert.pfx"
[IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:SIGNING_CERT_PFX_BASE64))
try {
    foreach ($file in $Files) {
        & $signtool.FullName sign /f $pfx /p $env:SIGNING_CERT_PASSWORD `
            /fd sha256 /tr http://timestamp.digicert.com /td sha256 `
            /d "Universal Death Counter" $file
        if ($LASTEXITCODE -ne 0) { throw "Signing failed for $file" }
    }
}
finally {
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
}
