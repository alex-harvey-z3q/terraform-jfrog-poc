#!/usr/bin/env pwsh
[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory)]
    [ValidateSet('setup', 'wait', 'bootstrap', 'init', 'validate', 'preflight', 'import', 'plan', 'apply', 'verify', 'verify-managed', 'test', 'drift', 'demo', 'persistence', 'reset')]
    [string]$Command,
    [string]$Confirm = ''
)

Import-Module (Join-Path $PSScriptRoot 'JFrog.Common.psm1') -Force

$imports = @{
    'module.security.artifactory_general_security.baseline'           = 'security'
    'module.security.artifactory_user_lock_policy.baseline'           = 'security-poc-lockout'
    'module.security.artifactory_password_expiration_policy.baseline' = 'security-poc-expiration'
}

function Setup {
    New-Item -ItemType Directory -Force -Path $Local | Out-Null
    if ($IsLinux -or $IsMacOS) { & chmod 700 $Local }
    $envFile = Join-Path $Root '.env'
    if (-not (Test-Path $envFile)) {
        $password = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(24)).ToLowerInvariant()
        Write-PrivateFile $envFile "POSTGRES_PASSWORD=$password`n"
    }
    Write-Output 'Local configuration ready; existing database password preserved.'
}

function Bootstrap {
    Write-Output "At http://localhost:8082 complete initial setup: activate trial licence, replace the default admin password, and create an expiring admin access token. The token is stored only in .local/admin-token (mode 0600)."
    $token = if ($env:JFROG_ACCESS_TOKEN) { $env:JFROG_ACCESS_TOKEN } else { Read-Host 'Admin access token' -AsSecureString | ConvertFrom-SecureString -AsPlainText }
    if (-not $token) { Fail 'An admin token is required' }
    foreach ($path in @($General, $Lock, $Expiry)) { Get-JFrogJson $path $token | Out-Null }
    Write-PrivateFile (Join-Path $Local 'admin-token') "$token`n"
    Write-Output 'Token accepted; all three configuration read endpoints are accessible.'
}

function Preflight {
    $token = Get-JFrogToken
    if ((Get-JFrogJson '/artifactory/api/system/version' $token).version -ne '7.161.15') { Fail 'This Terragrunt unit targets only the pinned 7.161.15 local lab' }
    foreach ($path in @($General, $Lock, $Expiry)) { Get-JFrogJson $path $token | Out-Null }
    Write-Output 'PASS: local version, credentials and configuration read APIs.'
}

function Import-Settings {
    Invoke-Terragrunt -Arguments @('init', '-input=false') | Out-Null
    $state = Join-Path $TerraformDirectory 'terraform.tfstate'
    $existing = if (Test-Path $state) { @((Invoke-TerraformRead -Arguments @('state', 'list') -Capture).Output -split "`r?`n") } else { @() }
    foreach ($entry in $imports.GetEnumerator()) {
        if ($existing -notcontains $entry.Key) { Invoke-Terragrunt -Arguments @('import', '-input=false', $entry.Key, $entry.Value) | Out-Null }
    }
    Write-Output 'All global settings are imported.'
}

function Get-Desired { (Invoke-TerraformRead -Arguments @('output', '-json', 'baseline') -Capture).Output | ConvertFrom-Json -AsHashtable }

function Verify-Managed {
    $expected = Get-Desired
    $general = Get-JFrogJson $General
    $lock = Get-JFrogJson $Lock
    $expiry = Get-JFrogJson $Expiry
    $actual = @{
        anonymous_access           = $general.anonAccessEnabled
        encryption_policy           = $general.passwordSettings.encryptionPolicy
        hide_unauthorized_resources = $general.hideUnauthorizedResources
        lockout_enabled             = $lock.enabled
        login_attempts              = $lock.loginAttempts
        expiration_enabled          = $expiry.enabled
        password_max_age            = $expiry.passwordMaxAge
        notification_email          = $expiry.notifyByEmail
    }
    $diff = @{}
    foreach ($key in $expected.Keys) {
        if ($null -eq $actual[$key] -or $actual[$key].GetType() -ne $expected[$key].GetType() -or $actual[$key] -cne $expected[$key]) {
            $diff[$key] = @{ expected = $expected[$key]; actual = $actual[$key] }
        }
    }
    if ($diff.Count) { $diff | ConvertTo-Json -Depth 8; Fail 'Configuration read-back differs from baseline' }
    $plan = Invoke-TerraformRead -Arguments @('plan', '-input=false', '-detailed-exitcode') -Allowed @(0, 2) -Capture
    if ($plan.ExitCode -ne 0) { Fail 'Expected a clean plan, but Terraform detected changes' }
    Write-Output 'PASS: Terraform-managed subset only; full security acceptance is separate.'
}

function Invoke-Drift {
    $baseline = Get-Desired
    $policy = Get-JFrogJson $Lock
    $policy.loginAttempts = [int]$baseline.login_attempts + 1
    Invoke-JFrogApi -Method PUT -Path $Lock -Body $policy | Out-Null
    if ((Get-JFrogJson $Lock).loginAttempts -ne ([int]$baseline.login_attempts + 1)) { Fail 'Drift injection did not persist' }
    Write-Output 'Changed only loginAttempts outside Terraform. Run make plan, then make apply.'
}

function New-Fixture {
    $suffix = [guid]::NewGuid().ToString('N').Substring(0, 12)
    [pscustomobject]@{
        Repository   = "poc-$suffix"
        Description  = "Unmanaged sentinel $suffix"
        Content      = "Artifactory security POC test artifact`n"
        CleanupPaths = [Collections.Generic.List[string]]::new()
    }
}

function Add-Fixture([object]$Fixture) {
    $repositoryPath = "/artifactory/api/repositories/$($Fixture.Repository)"
    $existing = Invoke-JFrogApi -Method GET -Path $repositoryPath -Allowed @(404)
    if ($existing.StatusCode -ne 404) { Fail 'Fixture repository already exists; refusing to overwrite it' }
    Invoke-JFrogApi -Method PUT -Path $repositoryPath -Body @{ rclass = 'local'; packageType = 'generic'; description = $Fixture.Description } | Out-Null
    $Fixture.CleanupPaths.Add($repositoryPath)
    $artifactPath = "/artifactory/$($Fixture.Repository)/fixture.txt"
    Invoke-JFrogApi -Method PUT -Path $artifactPath -Body $Fixture.Content -ContentType 'application/octet-stream' | Out-Null
    $Fixture.CleanupPaths.Add($artifactPath)
}

function Remove-Fixture([object]$Fixture) {
    $failures = [Collections.Generic.List[string]]::new()
    foreach ($path in @($Fixture.CleanupPaths | Select-Object -Reverse)) {
        try { Invoke-JFrogApi -Method DELETE -Path $path -Allowed @(200, 202, 204, 404) | Out-Null } catch { $failures.Add($_.Exception.Message) }
    }
    if ($failures.Count) { Fail ('Fixture cleanup incomplete: ' + ($failures -join '; ')) }
}

function Test-Fixture([object]$Fixture) {
    $artifactPath = "/artifactory/$($Fixture.Repository)/fixture.txt"
    $artifact = Invoke-JFrogApi -Method GET -Path $artifactPath
    if ($artifact.Content -cne $Fixture.Content) { Fail 'Bearer-token download did not return the seeded artifact' }
    Invoke-JFrogApi -Method GET -Path $artifactPath -Anonymous -Allowed @(401, 403, 404) | Out-Null
    if ((Get-JFrogJson "/artifactory/api/repositories/$($Fixture.Repository)").description -cne $Fixture.Description) { Fail 'Unmanaged repository description changed' }
    Write-Output 'PASS: bearer download and anonymous denial only; lockout/Basic checks remain manual.'
}

function Invoke-Integration {
    Verify-Managed
    $fixture = New-Fixture
    try { Add-Fixture $fixture; Test-Fixture $fixture } finally { Remove-Fixture $fixture }
}

function Invoke-Demo {
    Verify-Managed
    $fixture = New-Fixture
    try {
        Add-Fixture $fixture; Test-Fixture $fixture; Invoke-Drift
        $plan = Join-Path $Local 'drift.tfplan'
        $result = Invoke-Terragrunt -Arguments @('plan', '-input=false', '-detailed-exitcode', "-out=$plan") -Allowed @(0, 2) -Capture
        if ($result.ExitCode -ne 2) { Fail 'Terraform failed to detect injected drift' }
        $document = (Invoke-TerraformRead -Arguments @('show', '-json', $plan) -Capture).Output | ConvertFrom-Json -AsHashtable
        $changed = @($document.resource_changes | Where-Object { (@($_.change.actions) -join ',') -ne 'no-op' })
        if ($changed.Count -ne 1 -or $changed[0].address -ne 'module.security.artifactory_user_lock_policy.baseline') { Fail 'Drift plan contained unexpected resource changes' }
        $change = $changed[0].change
        $delta = @($change.before.Keys | Where-Object { $change.before[$_] -cne $change.after[$_] })
        if ((@($change.actions) -join ',') -ne 'update' -or $delta.Count -ne 1 -or $delta[0] -ne 'login_attempts') { Fail 'Drift plan did not contain exactly the lockout threshold update' }
        Invoke-Terragrunt -Arguments @('apply', '-input=false', $plan) | Out-Null
        Verify-Managed; Test-Fixture $fixture
        Write-Output 'PASS: drift detected precisely, remediated, and unrelated configuration preserved.'
    } finally {
        Invoke-Terragrunt -Arguments @('apply', '-input=false', '-auto-approve') | Out-Null
        Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Local 'drift.tfplan')
        Remove-Fixture $fixture
    }
}

function Invoke-Persistence {
    Verify-Managed
    Invoke-Process -File $Compose[0] -Arguments ($Compose[1..($Compose.Count - 1)] + @('stop', 'artifactory'))
    Invoke-Process -File $Compose[0] -Arguments ($Compose[1..($Compose.Count - 1)] + @('restart', 'postgres'))
    Invoke-Process -File $Compose[0] -Arguments ($Compose[1..($Compose.Count - 1)] + @('up', '-d', '--wait', '--wait-timeout', '60', 'postgres'))
    Invoke-Process -File $Compose[0] -Arguments ($Compose[1..($Compose.Count - 1)] + @('start', 'artifactory'))
    Wait-JFrogReady
    Verify-Managed
}

function Reset-Lab {
    if ($Confirm -ne 'delete-local-poc') { Fail 'Reset deletes only POC volumes/state. Use make reset CONFIRM=delete-local-poc' }
    Invoke-Process -File $Compose[0] -Arguments ($Compose[1..($Compose.Count - 1)] + @('down', '--volumes'))
    Get-ChildItem -Path $TerraformDirectory -Filter 'terraform.tfstate*' | Remove-Item -Force
    @('admin-token', 'drift.tfplan') | ForEach-Object { Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Local $_) }
    Write-Output 'Lab data/state removed. Repeat bootstrap and import after starting again.'
}

try {
    switch ($Command) {
        'setup'          { Setup }
        'wait'           { Wait-JFrogReady }
        'bootstrap'      { Bootstrap }
        'preflight'      { Preflight }
        'init'           { Invoke-Terragrunt -Arguments @('init', '-input=false') }
        'validate'       { Invoke-Terragrunt -Arguments @('validate') }
        'import'         { Import-Settings }
        'plan'           { Invoke-Terragrunt -Arguments @('plan', '-input=false') }
        'apply'          { Invoke-Terragrunt -Arguments @('apply') }
        'verify-managed' { Verify-Managed }
        'verify'         { Verify-Managed; & (Join-Path $PSScriptRoot 'Security.ps1') check; & (Join-Path $PSScriptRoot 'Security.ps1') audit; & (Join-Path $PSScriptRoot 'Security.ps1') inputs; Fail 'Full acceptance still requires the manual checks in docs/coverage.md; managed settings alone do not establish compliance' }
        'test'           { Invoke-Integration }
        'drift'          { Invoke-Drift }
        'demo'           { Invoke-Demo }
        'persistence'    { Invoke-Persistence }
        'reset'          { Reset-Lab }
    }
} catch {
    Write-Error "ERROR: $($_.Exception.Message)"
    exit 1
}
