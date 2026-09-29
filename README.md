# Artifactory security configuration POC

A disposable, localhost-only Artifactory lab for proving configuration-as-code and drift correction on **Administration → Security → General**. Terraform owns three baseline policies; Python manages documented deployment settings, checks effective configuration, and exercises a limited drift demo. The additional Basic Security Configuration is mapped in [coverage](docs/coverage.md).

**Status:** implementation is available; see [actual validation results](docs/results.md). Full integration acceptance requires a valid self-hosted trial licence. Offline tests are not evidence that the server accepts these APIs.

## Terraform and Python responsibilities

```text
                         Makefile commands
                                |
              +-----------------+------------------+
              |                                    |
              v                                    v
  Python: scripts/poc.py               Python: scripts/security.py
  Orchestration and tests              Additional configuration owner
  |                                    |
  +-- invokes Terraform CLI            +-- merges Access YAML:
  |   import / plan / apply            |   - no anonymous project access
  |             |                      |   - API-key creation/auth off
  |             v                      |   - Remember Me/autocomplete off
  |   Terraform:                       |   - suspension: 2 failures,
  |   modules/security-baseline        |     maximum delay 60 seconds
  |   Configuration owner              |
  |   - anonymous access off           +-- merges system.yaml:
  |   - encryption REQUIRED            |   - Platform Auditor feature on
  |   - permanent lock threshold 5     |
  |   - password expiry/emails off     +-- patches Artifactory API:
  |             |                      |   - hide unauthorised resources
  |             | provider API calls   |
  |             |                      | files + restart / API patch
  |             v                      v
  |   +---------------------------------------------------------+
  |   | Local Artifactory + Access services                      |
  |   | Docker Compose runs Artifactory and PostgreSQL           |
  |   +---------------------------------------------------------+
  |             |                                    |
  |             v                                    v
  +-- API read-back + clean plan        +-- running-config/API read-back
  +-- bearer/anonymous download tests   +-- readers/anonymous audit
  +-- inject test drift; Terraform      +-- validate private inputs
      restores its desired settings

  Manual / pending acceptance (neither tool completes these):
  Basic-auth exceptions + initial-admin disabling; SSH; login banner;
  idle timeout; readers deletion; role migration; exact lockout and
  suspension timing; remaining UI and behavioural checks.
```

Terraform and `security.py` own different settings; run their applies serially.
`poc.py` coordinates Terraform and checks its results rather than owning a
second copy of its baseline. Its drift demo deliberately changes the lockout
threshold temporarily to test Terraform remediation. The diagram describes
implemented responsibilities, not verified live compliance; see the
[coverage matrix](docs/coverage.md) for acceptance gates.

## Prerequisites

- Docker Engine with Compose, or a compatible Docker runtime (including Docker Desktop or Colima on macOS). Use a runtime whose licence permits your use.
- Approximately 4 CPUs and 8 GB memory available to the lab, and space for several GB of images/data.
- Terraform 1.5+ (below 2.0), Python 3.10+, PyYAML 6.0.3 (`python3 -m pip install -r requirements.txt` in your Python environment), and Make.
- A [self-hosted JFrog trial licence](https://jfrog.com/start-free/install/), for the self-hosted edition. Trial duration and eligibility must be confirmed with JFrog. Obtain the licence when ready for live tests.

Versions are pinned: Artifactory Pro 7.161.15 (multi-architecture digest), PostgreSQL 16.8, and `jfrog/artifactory` 12.11.13. The dependency lock includes macOS ARM64 and Linux AMD64/ARM64 checksums. The exact organisational version is still unknown.

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
make apply          # Terraform prompts before applying
make verify-managed # Read-back and clean plan for the Terraform subset
make security-apply # Additional settings, private backups and local container restart
make security-check # Service-generated Access state and API read-back
make security-audit # Read-only readers/anonymous dependency inventory
make verify         # Nonzero: remaining controls need separate operator evidence
```

The module disables anonymous access, requires encrypted client passwords (`REQUIRED`), and enables the permanent-lock policy with threshold 5. Other values for `login_attempts` are now rejected by validation. Existing password-expiry settings are preserved. Deployment automation adds Platform Auditor, project-anonymous restrictions, Remember Me/autocomplete disabling, API-key creation/authentication disabling, temporary-suspension configuration and global resource hiding. It owns separate fields from Terraform.

**This is not full compliance.** Basic-auth lockdown and exceptions, initial-admin disabling, SSH, the login dialog, exact suspension/lockout behaviour, 15-minute idle expiry, safe readers deletion and role migration require the documented inputs/manual acceptance. `make verify` deliberately cannot certify those from a local file.

Copy `config/security-inputs.example.json` to `.local/security-inputs.json`, restrict it to mode 0600, and fill in approved identities, banner title/text and the role-design reference. `make security-inputs` detects unresolved values; it does not configure JFrog or approve the contents. Keep all environment-specific values out of source control.

`make import` is safe to repeat. Do not use `terraform destroy`: these are global server policies, and provider deletion can disable them. Resources have `prevent_destroy`; removing their configuration can remove that protection. Dispose of the lab using the lifecycle commands below.

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

Validation runs Terraform formatting/schema validation and Python unit tests for transport errors, secret handling, fixture cleanup, YAML merge preservation, dependency-audit safety, TBD inputs, read-back failures and destructive-reset safeguards. No server credentials are required. Terraform init needs network access to download the signed provider. Live tests remain required.

## Troubleshooting

- **Docker connection failure:** start your Docker runtime and ensure your user can access it.
- **Port conflict:** stop the conflicting service or deliberately update both Compose and local clients; changing only Compose is insufficient.
- **Slow startup:** allocate sufficient runtime memory and inspect `docker compose logs --tail=100` locally. Logs can contain secrets; redact before sharing.
- **HTTP 401/403:** check licence activation, administrator token scope/expiry, and endpoint compatibility.
- **HTTP 404 or incompatible schema:** record the failed endpoint in the coverage report. These provider resources use legacy/private APIs. Do not downgrade silently or report a pass.
- **Database authentication error after changing .env:** changing the environment does not rotate an existing PostgreSQL volume's password. Restore the original value or explicitly reset the disposable lab.

The next gate is licence/token bootstrap for live writes, followed by the full coverage checklist and the missing organisational inputs. No organisation-owned instance is targeted by this lab.
