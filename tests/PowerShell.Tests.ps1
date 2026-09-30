BeforeAll {
    $root = Split-Path -Parent $PSScriptRoot
    Import-Module (Join-Path $root 'scripts/JFrog.Common.psm1') -Force
}

Describe 'PowerShell automation safety boundary' {
    It 'rejects remote or malformed API paths' {
        { Assert-LocalApiPath 'https://example.invalid' } | Should -Throw
        { Assert-LocalApiPath '//example.invalid' } | Should -Throw
        { Assert-LocalApiPath '/valid/path' } | Should -Not -Throw
    }

    It 'prefers an environment access token without printing it' {
        $previous = $env:JFROG_ACCESS_TOKEN
        try {
            $env:JFROG_ACCESS_TOKEN = 'private-token'
            Get-JFrogToken | Should -Be 'private-token'
        } finally { $env:JFROG_ACCESS_TOKEN = $previous }
    }

    It 'removes ambient Terraform routing flags' {
        $old = $env:TF_CLI_ARGS
        try {
            $env:TF_CLI_ARGS = '-destroy'
            $environment = Get-TerraformEnvironment -NoToken
            $environment.ContainsKey('TF_CLI_ARGS') | Should -BeFalse
            $environment.JFROG_URL | Should -Be 'http://localhost:8082'
        } finally { $env:TF_CLI_ARGS = $old }
    }

    It 'requires the exact local-reset confirmation before invoking Docker' {
        $result = & pwsh -NoProfile -File (Join-Path $root 'scripts/Poc.ps1') reset -Confirm 'no' 2>&1
        $LASTEXITCODE | Should -Be 1
        ($result -join "`n") | Should -Match 'Use make reset CONFIRM=delete-local-poc'
    }

    It 'rejects Terraform destroy mode in the PowerShell engine' {
        $result = & (Join-Path $root 'scripts/terraform-engine') apply -destroy 2>&1
        $LASTEXITCODE | Should -Be 1
        ($result -join "`n") | Should -Match 'destruction is disabled'
    }

    It 'uses PowerShell hooks and has no Python operational entry points' {
        $hooks = Get-Content -Raw (Join-Path $root 'examples/local/terragrunt.hcl')
        $hooks | Should -Match 'Security\.ps1'
        $hooks | Should -Not -Match 'POC_PYTHON|security\.py'
        Test-Path (Join-Path $root 'scripts/poc.py') | Should -BeFalse
        Test-Path (Join-Path $root 'scripts/security.py') | Should -BeFalse
    }

    It 'pins and loads the YAML parser used by the deployment hook' {
        $requirements = Import-PowerShellDataFile (Join-Path $root 'requirements.psd1')
        $requirements.RequiredModules.ModuleName | Should -Contain 'powershell-yaml'
        $requirements.RequiredModules.ModuleVersion | Should -Contain '0.4.12'
        Import-Module powershell-yaml -RequiredVersion 0.4.12
        $parsed = "security:`n  enabled: false" | ConvertFrom-Yaml
        $parsed.security.enabled | Should -BeFalse
    }
}
