[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
Import-Module (Join-Path $PSScriptRoot 'JFrog.Common.psm1') -Force
try {
    if ($Arguments -contains 'destroy' -or @($Arguments | Where-Object { $_ -match '^-destroy(?:=|$)' }).Count) { Fail 'Global-policy destruction is disabled; use the guarded lab reset' }
    $offline = @('init','validate','fmt','version','-version','--version','-help','--help','output','show','state','providers','get')
    $environment = Get-TerraformEnvironment -NoToken:($Arguments.Count -eq 0 -or $Arguments[0] -in $offline)
    Invoke-Process -File 'terraform' -Arguments $Arguments -Environment $environment
} catch { Write-Error "ERROR: $($_.Exception.Message)"; exit 1 }
