PYTHON ?= python3
COMPOSE = docker compose -f compose.yaml -p jfrog-security-poc
.DEFAULT_GOAL := help
.PHONY: help setup lab-up lab-down bootstrap init import plan apply verify test test-unit validate drift demo persistence reset
help:
	@echo 'setup lab-up bootstrap init import plan apply verify test drift demo persistence lab-down reset'
setup:
	$(PYTHON) scripts/poc.py setup
lab-up: setup
	$(COMPOSE) up -d --quiet-pull
	$(PYTHON) scripts/poc.py wait
lab-down:
	$(COMPOSE) down
bootstrap:
	$(PYTHON) scripts/poc.py bootstrap
init:
	terraform -chdir=examples/local init
import:
	$(PYTHON) scripts/poc.py import
plan:
	$(PYTHON) scripts/poc.py plan
apply:
	$(PYTHON) scripts/poc.py apply
verify:
	$(PYTHON) scripts/poc.py verify
test:
	$(PYTHON) scripts/poc.py test
test-unit:
	$(PYTHON) -m unittest discover -s tests -v
validate:
	terraform fmt -check -recursive
	terraform -chdir=examples/local validate
	$(PYTHON) -m unittest discover -s tests -v
drift:
	$(PYTHON) scripts/poc.py drift
demo:
	$(PYTHON) scripts/poc.py demo
persistence:
	$(PYTHON) scripts/poc.py persistence
reset:
	$(PYTHON) scripts/poc.py reset --confirm '$(CONFIRM)'

# Deployment-owned settings are separate from the Terraform subset.
.PHONY: security-apply security-check security-inputs verify-managed
security-apply:
	$(PYTHON) scripts/security.py apply
security-check:
	$(PYTHON) scripts/security.py check
security-inputs:
	$(PYTHON) scripts/security.py inputs
verify-managed:
	$(PYTHON) scripts/poc.py verify-managed
.PHONY: security-audit
security-audit:
	$(PYTHON) scripts/security.py audit
