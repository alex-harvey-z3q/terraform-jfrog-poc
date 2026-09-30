Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Root = Split-Path -Parent $PSScriptRoot
$script:Local = Join-Path $script:Root '.local'
$script:TerraformDirectory = Join-Path $script:Root 'examples/local'
$script:Compose = @('docker', 'compose', '-f', (Join-Path $script:Root 'compose.yaml'), '-p', 'jfrog-security-poc')
$script:Url = 'http://localhost:8082'
$script:General = '/artifactory/api/securityconfig'
$script:Lock = '/artifactory/api/security/userLockPolicy'
$script:Expiry = '/artifactory/api/security/configuration/passwordExpirationPolicy'

function Fail([string]$Message) { throw $Message }

function Write-PrivateFile([string]$Path, [string]$Content) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
    if ($IsLinux -or $IsMacOS) { & chmod 600 $Path; if ($LASTEXITCODE) { Fail 'Unable to protect local secret file' } }
}

function Get-JFrogToken {
    if ($env:JFROG_ACCESS_TOKEN) { return $env:JFROG_ACCESS_TOKEN.Trim() }
    $path = Join-Path $script:Local 'admin-token'
    if (Test-Path -LiteralPath $path) { return (Get-Content -Raw -LiteralPath $path).Trim() }
    Fail 'Activate the trial and run make bootstrap; no admin token is available'
}

function Assert-LocalApiPath([string]$Path) {
    if (-not $Path.StartsWith('/') -or $Path.StartsWith('//') -or $Path.Contains('://')) { Fail 'API paths must be local absolute paths' }
}

function Invoke-JFrogApi {
    param(
        [Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [object]$Body,
        [string]$Token,
        [switch]$Anonymous,
        [int[]]$Allowed = @(200..299),
        [string]$ContentType = 'application/json'
    )
    Assert-LocalApiPath $Path
    $headers = @{}
    if (-not $Anonymous) {
        if (-not $Token) { $Token = Get-JFrogToken }
        $headers.Authorization = "Bearer $Token"
    }
    $params = @{ Uri = "$script:Url$Path"; Method = $Method; Headers = $headers; MaximumRedirection = 0; SkipHttpErrorCheck = $true; TimeoutSec = 15 }
    if ($PSBoundParameters.ContainsKey('Body')) {
        if ($Body -is [string]) { $params.Body = $Body } else { $params.Body = $Body | ConvertTo-Json -Depth 32 -Compress }
        $params.ContentType = $ContentType
    }
    try { $response = Invoke-WebRequest @params } catch { Fail "$Method $Path`: connection failed ($($_.Exception.GetType().Name))" }
    if ($Allowed -notcontains [int]$response.StatusCode) { Fail "$Method $Path`: HTTP $($response.StatusCode); check licence, credentials and API compatibility" }
    [pscustomobject]@{ StatusCode = [int]$response.StatusCode; Content = [string]$response.Content }
}

function Get-JFrogJson([string]$Path, [string]$Token) {
    $response = Invoke-JFrogApi -Method GET -Path $Path -Token $Token
    try { return $response.Content | ConvertFrom-Json -AsHashtable } catch { Fail "$Path`: expected JSON, not HTML or an empty response" }
}

function Invoke-Process {
    param([string]$File, [string[]]$Arguments = @(), [switch]$Capture, [int[]]$Allowed = @(0), [hashtable]$Environment)
    $old = @{}
    if ($Environment) { foreach ($entry in $Environment.GetEnumerator()) { $old[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key); [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value) } }
    try {
        if ($Capture) { $output = & $File @Arguments 2>&1; $code = $LASTEXITCODE } else { & $File @Arguments; $code = $LASTEXITCODE }
    } finally {
        if ($Environment) { foreach ($entry in $Environment.GetEnumerator()) { [Environment]::SetEnvironmentVariable($entry.Key, $old[$entry.Key]) } }
    }
    if ($Allowed -notcontains $code) { Fail "$File failed (exit $code)" }
    if ($Capture) { return [pscustomobject]@{ ExitCode = $code; Output = ($output -join [Environment]::NewLine) } }
}

function Invoke-ProcessWithInput {
    param([string]$File, [string[]]$Arguments, [string]$InputText)
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $File; $start.UseShellExecute = $false; $start.RedirectStandardInput = $true; $start.RedirectStandardError = $true
    foreach ($argument in $Arguments) { [void]$start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::new(); $process.StartInfo = $start; [void]$process.Start()
    $process.StandardInput.Write($InputText); $process.StandardInput.Close(); $error = $process.StandardError.ReadToEnd(); $process.WaitForExit()
    if ($process.ExitCode) { Fail "$File failed while writing server configuration (exit $($process.ExitCode))" }
}

function Get-TerraformEnvironment([switch]$NoToken) {
    $env = @{}
    Get-ChildItem Env: | ForEach-Object { $env[$_.Name] = $_.Value }
    if (-not $NoToken) { $env.JFROG_ACCESS_TOKEN = Get-JFrogToken }
    $env.JFROG_URL = $script:Url; $env.TF_IN_AUTOMATION = '1'
    @($env.Keys) | Where-Object { $_ -like 'TF_CLI_ARGS*' -or $_ -like 'TF_VAR_*' -or $_ -in @('TF_DATA_DIR','TF_WORKSPACE') } | ForEach-Object { $env.Remove($_) }
    $env
}

function Get-Terragrunt {
    $candidate = Get-Command terragrunt -ErrorAction SilentlyContinue
    if ($candidate) { return $candidate.Source }
    $local = Join-Path $script:Local 'bin/terragrunt'
    if (Test-Path -LiteralPath $local) { return $local }
    Fail 'Install Terragrunt 1.1.6 or put it in .local/bin/terragrunt'
}

function Invoke-Terragrunt {
    param([string[]]$Arguments, [switch]$Capture, [int[]]$Allowed = @(0))
    $environment = Get-TerraformEnvironment -NoToken:($Arguments.Count -eq 0 -or $Arguments[0] -notin @('plan','apply','import','refresh'))
    @($environment.Keys) | Where-Object { $_ -like 'TG_*' -or $_ -like 'TERRAGRUNT_*' } | ForEach-Object { $environment.Remove($_) }
    $environment.POC_PWSH = (Get-Command pwsh -ErrorAction Stop).Source
    Invoke-Process -File (Get-Terragrunt) -Arguments (@('--working-dir', $script:TerraformDirectory, 'run', '--') + $Arguments) -Capture:$Capture -Allowed $Allowed -Environment $environment
}

function Invoke-TerraformRead {
    param([string[]]$Arguments, [switch]$Capture, [int[]]$Allowed = @(0))
    if ($env:TG_CTX_COMMAND -eq 'apply') {
        if ($Arguments.Count -eq 0 -or $Arguments[0] -notin @('output','plan','show','state')) { Fail 'Only verification commands may call Terraform inside an apply hook' }
        return Invoke-Process -File 'terraform' -Arguments (@("-chdir=$PWD") + $Arguments) -Capture:$Capture -Allowed $Allowed -Environment (Get-TerraformEnvironment)
    }
    Invoke-Terragrunt -Arguments $Arguments -Capture:$Capture -Allowed $Allowed
}

function Wait-JFrogReady {
    $deadline = [DateTime]::UtcNow.AddMinutes(10)
    while ([DateTime]::UtcNow -lt $deadline) {
        try { if ((Invoke-JFrogApi -Method GET -Path '/artifactory/api/system/ping' -Anonymous).Content.Trim() -eq 'OK') { Write-Output "Artifactory API ready at $script:Url"; return } } catch {}
        Start-Sleep -Seconds 5
    }
    Fail 'Readiness timed out after 10 minutes. Inspect docker compose logs --tail=100 locally; logs may contain secrets.'
}

Export-ModuleMember -Function * -Variable Root,Local,TerraformDirectory,Compose,Url,General,Lock,Expiry
