# Code signing

Unsigned Windows apps trigger SmartScreen's **"Windows protected your PC /
Unknown publisher"** warning, and they are more likely to be flagged by
antivirus. CI signs the app `.exe` and the installer as soon as signing is
set up, and skips signing until then. Nothing else has to change.

The project uses **[SignPath Foundation](https://signpath.org/)**, which
signs open-source projects for free. The certificate is issued to SignPath
Foundation, and each release is signed after you approve it.

## 1. Apply (once)

1. Make sure the basics are in place (they already are for this repository):
   - an OSI licence (MIT)
   - a public repository
   - releases built by GitHub Actions
   - at least one published release
2. Turn on two-factor authentication for your GitHub account. SignPath requires it.
3. Apply at **https://signpath.org/apply** with:
   - project: DePhantom Universal Death Counter
   - repository: https://github.com/Jvn1604/UniversalDeathCounter
   - what gets signed: the Windows app and installer
4. Wait for approval. They review by hand, which can take a few days to a few weeks.

## 2. Set up the project on SignPath

Once approved, you get access to **https://app.signpath.io**:

1. **Project:** create one with the slug `UniversalDeathCounter`. Link it to
   this GitHub repository as its source (trusted build system: GitHub.com).
2. **Artifact configuration:** create one with the slug **`exe`**, using:
   ```xml
   <?xml version="1.0" encoding="utf-8"?>
   <artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
     <zip-file>
       <pe-file path="*.exe">
         <authenticode-sign />
       </pe-file>
     </zip-file>
   </artifact-configuration>
   ```
   GitHub hands each file over as a zip. This signs the `.exe` inside it,
   which covers both the app and the installer.
3. **Signing policy:** the release signing policy SignPath Foundation gives
   you, with the slug **`release-signing`**.
4. **API token:** create a CI user with *Submitter* rights on that policy
   and copy its API token.
5. **Organization ID:** copy it from *Settings* in SignPath.

## 3. Connect it to GitHub

In the repository: **Settings → Secrets and variables → Actions**.

| Kind | Name | Value |
|---|---|---|
| Secret | `SIGNPATH_API_TOKEN` | the CI user's API token |
| Variable | `SIGNPATH_ORGANIZATION_ID` | your organization ID |
| Variable (only if your slugs differ) | `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_POLICY_SLUG` | your slugs |

On the next release, CI signs as soon as the `v*` tag is pushed:

1. The **Build Windows Executable** job uploads the app `.exe` to SignPath.
2. SignPath waits for your approval, which you give in the SignPath website or app.
3. The job carries on with the signed file and builds the installer around it.
4. The installer goes through steps 1–3 the same way.

Pull requests and normal `main` builds are not signed.

To check a download, right-click it → **Properties → Digital Signatures**. It
should show *SignPath Foundation*.

SmartScreen reputation builds up over time. Even signed builds may show the
warning for their first few downloads.

## 4. Code signing policy (for the README, once approved)

SignPath Foundation asks the project to state its policy where users see
it. Add this to the README when the application is approved:

> **Code signing policy:** free code signing provided by
> [SignPath.io](https://about.signpath.io), certificate by
> [SignPath Foundation](https://signpath.org).
> Releases are built by GitHub Actions from this repository and signed only
> after approval by the maintainer (Jeeventhiran Sivanantham).
> **Privacy:** this program does not send any information to other networked
> systems unless the user asks for it: the update check, theme downloads and
> game artwork, all described in the README.

## Alternative: your own certificate (`.pfx`)

If you buy an OV certificate instead (Sectigo, Certum, SSL.com and others;
Certum has a cheaper open-source option):

1. Convert the certificate to base64 (PowerShell):
   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("codesign.pfx")) | Set-Clipboard
   ```
2. Add these repository secrets:
   - `SIGNING_CERT_PFX_BASE64`: the base64 text
   - `SIGNING_CERT_PASSWORD`: the `.pfx` password

Every CI build is then signed with `packaging/sign.ps1`, timestamped
through DigiCert.

## macOS

The Mac app isn't notarized, so Gatekeeper asks the first time: right-click
→ **Open**. Notarization needs a paid Apple Developer Program membership
($99 a year).
