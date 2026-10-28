# Code signing

Unsigned Windows apps trigger SmartScreen's **"Windows protected your PC /
Unknown publisher"** warning, and they are more likely to be flagged by
antivirus. CI can sign both the app `.exe` and the installer. It does this
automatically once a certificate is configured, and skips signing until
then.

## 1. Get a code-signing certificate

Pick one:

| Option | Cost | Notes |
|---|---|---|
| [SignPath Foundation](https://signpath.org/) | Free for OSS | Signs open-source projects for free after an application. Uses its own GitHub Action instead of the `.pfx` flow below. |
| [Azure Trusted Signing](https://learn.microsoft.com/azure/trusted-signing/) | Low monthly fee | Microsoft-run; needs identity validation. Also has its own GitHub Action. |
| OV certificate (Sectigo, Certum, SSL.com, …) | Paid yearly | Gives a `.pfx` you can use with the steps below. Certum has a cheaper "Open Source Code Signing" option. |

SmartScreen reputation builds up over time. Even signed builds may show
the warning for their first few downloads.

## 2. Add the certificate to GitHub (for a `.pfx`)

1. Convert the certificate to base64 (PowerShell):
   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("codesign.pfx")) | Set-Clipboard
   ```
2. In the repo: **Settings → Secrets and variables → Actions → New repository secret**
   - `SIGNING_CERT_PFX_BASE64`: paste the base64 text
   - `SIGNING_CERT_PASSWORD`: the `.pfx` password

On the next CI run, the **Sign executable** and **Sign installer** steps
run with `packaging/sign.ps1`, timestamped through DigiCert. To check a
download, right-click it → **Properties → Digital Signatures**.
