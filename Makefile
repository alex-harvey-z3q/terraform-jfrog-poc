PWSH ?= pwsh
TERRAGRUNT ?= $(if $(wildcard .local/bin/terragrunt),$(CURDIR)/.local/bin/terragrunt,terragrunt)
COMPOSE = docker compose -f compose.yaml -p jfrog-security-poc
.DEFAULT_GOAL := help
.PHONY: help setup lab-up lab-down bootstrap init import plan apply verify test test-unit validate drift demo persistence reset
help:
	@echo 'setup lab-up bootstrap init import plan apply verify test drift demo persistence lab-down reset'
setup:
	$(PWSH) -NoProfile -File scripts/Poc.ps1 setup
lab-up: setup
	$(COMPOSE) up -d --quiet-pull
	$(PWSH) -NoProfile -File scripts/Poc.ps1 wait
lab-down:
	$(COMPOSE) down
bootstrap:
	$(PWSH) -NoProfile -File scripts/Poc.ps1 bootstrap
init:
	$(PWSH) -NoProfile -File scripts/Poc.ps1 init
import:
	$(PWSH) -NoProfile -File scripts/Poc.ps1 import
plan:
	$(PWSH) -NoProfile -File scripts/Poc.ps1 plan
apply:
	$(PWSH) -NoProfile -File scripts/Poc.ps1 apply
verify:
	$(PWSH) -NoProfile -File scripts/Poc.ps1 verify
test:
	$(PWSH) -NoProfile -File scripts/Poc.ps1 test
test-unit:
	$(PWSH) -NoProfile -Command 'Invoke-Pester -Path tests -Output Detailed'
validate:
	$(TERRAGRUNT) hcl fmt --check
	$(TERRAGRUNT) hcl validate
	terraform fmt -check -recursive
	$(PWSH) -NoProfile -File scripts/Poc.ps1 validate
	$(PWSH) -NoProfile -Command 'Invoke-Pester -Path tests -Output Detailed'
drift:
	$(PWSH) -NoProfile -File scripts/Poc.ps1 drift
demo:
	$(PWSH) -NoProfile -File scripts/Poc.ps1 demo
persistence:
	$(PWSH) -NoProfile -File scripts/Poc.ps1 persistence
reset:
	$(PWSH) -NoProfile -File scripts/Poc.ps1 reset -Confirm '$(CONFIRM)'

# Deployment-owned settings are separate from the Terraform subset.
.PHONY: security-apply security-check security-inputs verify-managed
# Compatibility alias: configuration writes now run through Terragrunt hooks.
security-apply: apply
security-check:
	$(PWSH) -NoProfile -File scripts/Security.ps1 check
security-inputs:
	$(PWSH) -NoProfile -File scripts/Security.ps1 inputs
verify-managed:
	$(PWSH) -NoProfile -File scripts/Poc.ps1 verify-managed
.PHONY: security-audit
security-audit:
	$(PWSH) -NoProfile -File scripts/Security.ps1 audit
