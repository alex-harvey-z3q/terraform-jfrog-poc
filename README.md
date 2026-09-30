# Artifactory security configuration POC

A disposable, localhost-only Artifactory lab for proving configuration-as-code and drift correction on **Administration → Security → General**. Terragrunt coordinates Terraform and Python hooks. Terraform owns three baseline policies; Python manages additional deployment settings and verifies effective configuration. The additional Basic Security Configuration is mapped in [coverage](docs/coverage.md).

**Status:** implementation is available; see [actual validation results](docs/results.md). Full integration acceptance requires a valid self-hosted trial licence. Offline tests are not evidence that the server accepts these APIs.

## Terragrunt, Terraform and Python responsibilities

```text
  make import / plan / apply
              |
              v
  Terragrunt: examples/local/terragrunt.hcl
  |
  +-- BEFORE plan / apply / import: Python poc.py preflight
  |     Check credentials, local server version and read APIs
  |
  +-- BEFORE apply: Python security.py preflight
  |     Check existing YAML, pending files and API schema (read only)
  |
  +-- TERRAFORM: modules/security-baseline
  |     Provider manages through the Artifactory API:
  |       - anonymous access off
  |       - password encryption REQUIRED
  |       - permanent lock threshold 5
  |       - password expiry/emails off
  |
  +-- AFTER successful apply: Python security.py apply
  |     Access YAML + system.yaml + restart:
  |       - no anonymous project access
  |       - API-key creation/authentication off
  |       - Remember Me/password autocomplete off
  |       - suspension: 2 failures, maximum delay 60 seconds
  |       - Platform Auditor feature on
  |     Artifactory API patch:
  |       - hide unauthorised resources
  |
  +-- AFTER success: Python poc.py verify-managed
  |     Terraform policy read-back + clean Terraform plan
  |
  +-- AFTER success: Python security.py check
        Deployment configuration/API read-back

  All settings target the local Artifactory + Access services.
  Docker Compose runs Artifactory and PostgreSQL.

  Manual / pending acceptance:
  Basic-auth exceptions + initial-admin disabling; SSH; login banner;
  idle timeout; readers deletion; role migration; exact timing and UI tests.
```

Hooks run in the order shown. A failed preflight stops Terraform; a failed
Terraform apply skips configuration hooks; a failed after-hook stops the
remaining checks and makes the command fail. Plan/import have no Python
configuration writes. Python-managed changes are outside Terraform's plan and
state; a clean plan covers only Terraform's policies.

Terraform and Python continue to own different settings. The full coverage
and manual acceptance gates remain in [coverage](docs/coverage.md).

## Prerequisites

- Docker Engine with Compose, or a compatible Docker runtime (including Docker Desktop or Colima on macOS). Use a runtime whose licence permits your use.
- Approximately 4 CPUs and 8 GB memory available to the lab, and space for several GB of images/data.
- Terragrunt **1.1.6**, Terraform 1.5+ (below 2.0), Python 3.10+, PyYAML 6.0.3 (`python3 -m pip install -r requirements.txt` in your Python environment), and Make.
- A [self-hosted JFrog trial licence](https://jfrog.com/start-free/install/), for the self-hosted edition. Trial duration and eligibility must be confirmed with JFrog. Obtain the licence when ready for live tests.

Versions are pinned: Artifactory Pro 7.161.15 (multi-architecture digest), PostgreSQL 16.8, and `jfrog/artifactory` 12.11.13. The dependency lock includes macOS ARM64 and Linux AMD64/ARM64 checksums. The exact organisational version is still unknown. Terragrunt is pinned in
`examples/local/terragrunt.hcl`. Install that version on PATH or place its
executable at `.local/bin/terragrunt`. A checksum-verified macOS ARM64 copy has
been installed at that local path on this machine; it is not committed.
See [Terragrunt installation](https://docs.terragrunt.com/getting-started/install/).

## Start and activate

From this directory:

```sh
make setup          # Generates a random local database password; preserves existing .env
make lab-up         # Downloads images, starts containers, waits up to 10 minutes
```

Open <http://localhost:8082>. Finish the initial setup wizard, activate your trial, change the default administrator password, and create an expiring administrator access token. Initial factory credentials are `admin` / `password`; replace them immediately during setup. Full policy acceptance requires tested external administration and approved recovery accounts before disabling Basic authentication and the initial administrator. See the [transition procedure](docs/coverage.md#private-inputs-and-basic-auth-transition).

```sh
make bootstrap      # Prompts privately for the token and checks all configuration read APIs
```

The token is saved in `.local/admin-token` with mode 0600. Alternatively, supply `JFROG_ACCESS_TOKEN` in your shell. Do not put the licence, token, passwords, Terraform state, or saved plans in Git. `.env` and `.local` are ignored. Bootstrap does not automate registration, licence acquisition, or the UI wizard.

Both Terraform and the Python client are fixed to localhost:8082. This lab deliberately has no production-target flag. PostgreSQL has no published host port; Artifactory host ports 8081 and 8082 bind only to loopback. HTTP is for this local synthetic test environment only.

## Apply the baseline

```sh
make import         # Initialises Terraform, imports the three existing singleton policies
make plan           # Review intended changes
make apply          # Terragrunt preflights, Terraform apply, Python apply/check hooks
make verify-managed # Optional standalone Terraform-subset verification
make security-check # Service-generated Access state and API read-back
make security-audit # Read-only readers/anonymous dependency inventory
make verify         # Nonzero: remaining controls need separate operator evidence
```

`make init`, `make import`, `make plan` and `make apply` now use Terragrunt.
Terraform still prompts for apply approval. `make security-apply` is retained as
an alias for `make apply`, so it cannot bypass the hook sequence. Bootstrap,
Docker lifecycle, optional audits and behavioural tests remain explicit Python
commands; they are not automatically run on every Terraform operation.

For direct use (when Terragrunt is on PATH):

```sh
cd examples/local
terragrunt run -- init
terragrunt run -- plan
terragrunt run -- apply
```

The hooks use `python3` by default; set `POC_PYTHON` to the Python executable
containing PyYAML if needed. Make's Python wrapper uses its own interpreter for
hooks. `scripts/terraform-engine` injects the token from the existing environment
or `.local/admin-token` into Terraform's process environment. No token is put in
HCL, command arguments or generated backend files. Use a Python environment
where `python3` is available on PATH for the engine launcher.

The module disables anonymous access, requires encrypted client passwords (`REQUIRED`), and enables the permanent-lock policy with threshold 5. Other values for `login_attempts` are now rejected by validation. Existing password-expiry settings are preserved. Deployment automation adds Platform Auditor, project-anonymous restrictions, Remember Me/autocomplete disabling, API-key creation/authentication disabling, temporary-suspension configuration and global resource hiding. It owns separate fields from Terraform.

**This is not full compliance.** Basic-auth lockdown and exceptions, initial-admin disabling, SSH, the login dialog, exact suspension/lockout behaviour, 15-minute idle expiry, safe readers deletion and role migration require the documented inputs/manual acceptance. `make verify` deliberately cannot certify those from a local file.

Copy `config/security-inputs.example.json` to `.local/security-inputs.json`, restrict it to mode 0600, and fill in approved identities, banner title/text and the role-design reference. `make security-inputs` detects unresolved values; it does not configure JFrog or approve the contents. Keep all environment-specific values out of source control.

`make import` is safe to repeat. Do not use `terraform destroy`: these are global server policies, and provider deletion can disable them. Resources have `prevent_destroy`; removing their configuration can remove that protection. Dispose of the lab using the lifecycle commands below.

## State, cache and hook failure handling

Terragrunt 1.1 executes from `.terragrunt-cache`, even with a local source.
The source includes the repository layout so relative module paths resolve.
The generated local backend points to the **existing**
`examples/local/terraform.tfstate`; resource addresses and provider lock hashes
remain unchanged. No state move or re-import is needed for an already imported
lab. Private `.local`/`.env` files and state are excluded from source copies;
the committed provider lock file is generated verbatim in the cache and init uses `-lockfile=readonly`. Update provider checksums explicitly in the source lock file when upgrading. Cache files are ignored by Git.

Inside the verification hook, Python calls Terraform directly in the initialized
cache to avoid recursive hooks. Standalone verification uses Terragrunt.
Always use this unit's default workspace; alternative workspaces/backends and
production targets are not supported by this lab.

Before apply, hooks require the current Access configuration file and a working
administrator token. The current lab still lacks these prerequisites. No live
configuration changes were made as part of the migration.

An after-hook failure does **not** roll back a successful Terraform apply.
Inspect the failure and private deployment backups, fix the cause, then rerun
`make apply`; hooks also execute when Terraform has no changes. The final checks
certify only the managed subset. `make verify` retains its separate, failing
manual-acceptance gate.

## Run acceptance tests

```sh
make test           # Terraform subset, bearer download and anonymous denial only
make demo           # Tests + drift injection + exact plan assertion + remediation + clean plan
make persistence    # Restart and verify the Terraform subset persists
```

`make demo` applies remediation automatically to this local instance. A private repository has a random POC-only name. Tests verify bearer-token access before anonymous denial and clean up their own fixture. They do not count password failures or claim lockout: Basic lockdown and REQUIRED encryption invalidate the old password-based test. Follow the timed acceptance procedure in the coverage document. A repository description is an unmanaged sentinel checked after apply. API errors and unsupported endpoints fail tests; they are never reported as successful denials or skipped controls.

To show drift manually:

```sh
make drift          # Changes only the server's login-attempt threshold, from 5 to 6
make plan           # Should propose restoring it to 5
make apply
make verify-managed
```

Keep the displayed plan and test outcome as evidence, excluding secrets. The automated demo validates that only `login_attempts` changes on the expected Terraform resource and removes its saved plan after use. Do not run multiple test/demo/reset workflows concurrently.

## Stop, restart, and rebuild

```sh
make lab-down       # Removes containers/network; preserves data and Terraform state
make lab-up         # Reuses that data
```

For the explicit rebuild acceptance test, first run `make demo`, then:

```sh
make reset CONFIRM=delete-local-poc
make lab-up
# Repeat UI activation/password setup with a valid licence and a new token.
make bootstrap
make import
make apply
make demo
```

Reset removes only this Compose project's volumes, local Terraform state/backups, saved drift plan, and saved admin token. It retains the generated database password and downloaded images. An expired trial must be resolved through JFrog; resetting the lab does not extend the licence.

## Offline checks

```sh
make init
make validate
```

Validation runs Terragrunt HCL formatting/validation, Terraform formatting/schema validation and Python tests for transport errors, secret handling, fixture cleanup, YAML merge preservation, dependency-audit safety, TBD inputs, read-back failures and destructive-reset safeguards. The hook integration tests execute the real Terragrunt binary with inert Terraform/Python executables, covering ordering, failure propagation, plan safety and cache/state handling. No server credentials are required. Terraform init needs network access to download the signed provider. Live tests remain required.

## Troubleshooting

- **Docker connection failure:** start your Docker runtime and ensure your user can access it.
- **Port conflict:** stop the conflicting service or deliberately update both Compose and local clients; changing only Compose is insufficient.
- **Slow startup:** allocate sufficient runtime memory and inspect `docker compose logs --tail=100` locally. Logs can contain secrets; redact before sharing.
- **HTTP 401/403:** check licence activation, administrator token scope/expiry, and endpoint compatibility.
- **HTTP 404 or incompatible schema:** record the failed endpoint in the coverage report. These provider resources use legacy/private APIs. Do not downgrade silently or report a pass.
- **Database authentication error after changing .env:** changing the environment does not rotate an existing PostgreSQL volume's password. Restore the original value or explicitly reset the disposable lab.

The next gate is licence/token bootstrap for live writes, followed by the full coverage checklist and the missing organisational inputs. No organisation-owned instance is targeted by this lab.
