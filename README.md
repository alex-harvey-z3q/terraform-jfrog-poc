# Artifactory security configuration POC

A disposable, localhost-only Artifactory lab for proving configuration-as-code and drift correction on **Administration → Security → General**. Terraform owns the baseline; Python checks API values, exercises authentication, and injects controlled drift.

**Status:** implementation is available; see [actual validation results](docs/results.md). Full integration acceptance requires a valid self-hosted trial licence. Offline tests are not evidence that the server accepts these APIs.

## Prerequisites

- Docker Engine with Compose, or a compatible Docker runtime (including Docker Desktop or Colima on macOS). Use a runtime whose licence permits your use.
- Approximately 4 CPUs and 8 GB memory available to the lab, and space for several GB of images/data.
- Terraform 1.5+ (below 2.0), Python 3.10+, and Make.
- A [self-hosted JFrog trial licence](https://jfrog.com/start-free/install/), currently advertised as 30 days. No cloud account is needed. Obtain the licence when ready for live tests.

Versions are pinned: Artifactory Pro 7.161.15 (multi-architecture digest), PostgreSQL 16.8, and `jfrog/artifactory` 12.11.13. The dependency lock includes macOS ARM64 and Linux AMD64/ARM64 checksums. The exact organisational version is still unknown.

## Start and activate

From this directory:

```sh
make setup          # Generates a random local database password; preserves existing .env
make lab-up         # Downloads images, starts containers, waits up to 10 minutes
```

Open <http://localhost:8082>. Finish the initial setup wizard, activate your trial, change the default administrator password, and create an expiring administrator access token. Initial factory credentials are `admin` / `password`; replace them immediately during setup. Do not configure an external IdP or disable Basic authentication in this disposable lab.

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
make verify         # Independent API read-back, followed by a no-change Terraform plan
```

The module disables anonymous access, enables lockout at 5 failed attempts, keeps password encryption `SUPPORTED`, and disables periodic password expiration and expiration emails. A required but inactive expiration-age field is set to 90 days. These are POC defaults, not an approved production policy. See [coverage and API caveats](docs/coverage.md).

`make import` is safe to repeat. Do not use `terraform destroy`: these are global server policies, and provider deletion can disable them. Resources have `prevent_destroy`; removing their configuration can remove that protection. Dispose of the lab using the lifecycle commands below.

## Run acceptance tests

```sh
make test           # Read-back, clean plan, anonymous/authorised downloads, explicit lockout
make demo           # Tests + drift injection + exact plan assertion + remediation + clean plan
make persistence    # Restart existing containers and verify the baseline persists
```

`make demo` applies remediation automatically to this local instance. Test users, a private repository, and a permission target have random POC-only names. Tests verify authenticated access before testing denial, confirm lockout via the locked-users API, and clean up their own fixtures. A repository description is an unmanaged sentinel checked after apply. API errors and unsupported endpoints fail tests; they are never reported as successful denials or skipped controls.

To show drift manually:

```sh
make drift          # Changes only the server's login-attempt threshold, from 5 to 6
make plan           # Should propose restoring it to 5
make apply
make verify
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

Validation runs Terraform formatting/schema validation and Python unit tests for transport errors, secret handling, fixture cleanup, and destructive-reset safeguards. No server credentials are required. Terraform init needs network access to download the signed provider. Live tests remain required.

## Troubleshooting

- **Docker connection failure:** start your Docker runtime and ensure your user can access it.
- **Port conflict:** stop the conflicting service or deliberately update both Compose and local clients; changing only Compose is insufficient.
- **Slow startup:** allocate sufficient runtime memory and inspect `docker compose logs --tail=100` locally. Logs can contain secrets; redact before sharing.
- **HTTP 401/403:** check licence activation, administrator token scope/expiry, and Basic authentication availability.
- **HTTP 404 or incompatible schema:** record the failed endpoint in the coverage report. These provider resources use legacy/private APIs. Do not downgrade silently or report a pass.
- **Database authentication error after changing .env:** changing the environment does not rotate an existing PostgreSQL volume's password. Restore the original value or explicitly reset the disposable lab.

The next deployment gate is confirming the organisation's self-hosted edition/version and security policy, then repeating acceptance tests against an appropriate non-production instance.
