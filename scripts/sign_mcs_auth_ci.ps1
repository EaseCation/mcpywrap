$ErrorActionPreference = 'Stop'
# Secrets are read only in this trusted CI step, after native compilation has completed.
if (!$env:MCS_BRIDGE_SIGNING_PFX -or !$env:MCS_BRIDGE_SIGNING_PASSWORD) { throw 'Code-signing secrets are not configured' }
$publisher = Get-Content native/mcs_auth/publisher.json -Raw | ConvertFrom-Json
$pfxPath = Join-Path $env:RUNNER_TEMP ('mcpy-signing-' + [guid]::NewGuid().ToString('N') + '.pfx')
$certificate = $null
try {
    [IO.File]::WriteAllBytes($pfxPath, [Convert]::FromBase64String($env:MCS_BRIDGE_SIGNING_PFX))
    $password = ConvertTo-SecureString $env:MCS_BRIDGE_SIGNING_PASSWORD -AsPlainText -Force
    $certificate = Import-PfxCertificate -FilePath $pfxPath -Password $password -CertStoreLocation Cert:\CurrentUser\My
    if ($certificate.Thumbprint -ne $publisher.thumbprint) { throw 'Signing secret does not match the pinned publisher certificate' }
    # The signing subprocess does not need the encrypted PFX or its password in its environment.
    Remove-Item Env:\MCS_BRIDGE_SIGNING_PFX
    Remove-Item Env:\MCS_BRIDGE_SIGNING_PASSWORD
    python scripts/build_mcs_auth_bridge.py --sign-only --output mcpywrap/mcstudio/bridge_payload --sign-thumbprint $certificate.Thumbprint
    if ($LASTEXITCODE -ne 0) { throw 'Bridge signing failed' }
} finally {
    if (Test-Path -LiteralPath $pfxPath) { Remove-Item -LiteralPath $pfxPath -Force }
    if ($certificate) { Remove-Item -LiteralPath ('Cert:\CurrentUser\My\' + $certificate.Thumbprint) -DeleteKey -Force }
}
