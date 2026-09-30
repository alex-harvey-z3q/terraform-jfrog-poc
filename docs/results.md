# Validation evidence

Run date: 2026-09-29. Environment: macOS ARM64, Docker Engine 29.4.3, Compose 5.1.3, Terraform 1.15.6, Python 3.12.12. Docker reports 10 CPUs and approximately 8 GB RAM allocated.

| Check | Result |
| --- | --- |
| Artifactory 7.161.15 manifest | Verified ARM64 and AMD64 images; multi-platform digest pinned |
| PostgreSQL 16.8 manifest | Digest pinned; PostgreSQL 16 is documented as supported from Artifactory 7.98 |
| Provider 12.11.13 download | HashiCorp-partner signature verified by Terraform |
| Provider dependency lock | Checksums recorded for darwin_arm64, linux_amd64, linux_arm64 |
| Provider source inspection | Resource schemas, import identifiers, and legacy API mappings confirmed |
| Compose configuration | `docker compose config --quiet` passed |
| Terraform formatting | Passed |
| Terraform schema validation | Passed; provider execution required access to a local plugin socket outside the agent sandbox |
| Python offline tests | 11 passed |
| Missing-credential behaviour | `verify` fails clearly without attempting configuration writes |
| Container startup / HTTP readiness | Passed after clean bootstrap: API ping 200/OK, UI 200, router health 200 with all services healthy |
| Actual server version | Authenticated read-only version API reports 7.161.15 |
| Configuration API reads | All three endpoints return HTTP 200 with expected top-level fields using factory bootstrap credentials; writes remain untested |
| Disposable volume reset / clean bootstrap | Exercised successfully during startup recovery; not a baseline rebuild acceptance pass |
| Licence activation / admin-token bootstrap | Pending: user does not yet have a trial licence |
| Terraform imports and baseline writes | Not run; requires activated instance and admin token |
| Live read-back, auth, lockout, drift/remediation | Not run; requires activated instance and admin token |
| Persistence / full rebuild acceptance | Not run; requires baseline apply and licence reactivation on rebuild |

The implementation is not yet an accepted end-to-end POC. Offline tests and schema validation do not prove the selected provider's legacy APIs work on Artifactory 7.161.15. The real acceptance commands are `make import`, `make apply`, `make test`, `make demo`, and `make persistence`, followed by the documented reset/rebuild sequence.

No organisation-owned instance has been accessed or changed. No licence or administrator token has been acquired or stored during implementation.

## Startup recovery

During implementation, pinning the PostgreSQL digest after the first Compose launch recreated the database container while Artifactory was initialising. The partial database then caused an upgrade/licence error. Only the new, empty POC volumes were reset, and the finished configuration booted cleanly with both image digests already pinned. PostgreSQL is healthy and all router services report healthy. The persistence command now stops Artifactory before restarting PostgreSQL, waits for database health, then starts Artifactory.

The lab is left running at http://localhost:8082/ui/ for the initial setup wizard. Factory administrator credentials have not been changed; replace them during setup. No other containers or data were modified.

## Basic Security Configuration update (2026-09-29)

The original table above records the earlier POC, before the additional specification. Its old authentication/lockout test is no longer the acceptance mechanism. No new live writes were performed during this update.

- Terraform encryption changed to REQUIRED; threshold input constrained to 5.
- Added deployment automation for Access settings, Platform Auditor, and global resource hiding. Added private input validation and a read-only readers/anonymous dependency audit.
- Removed the old Basic-success/rapid-lockout assertions. Bearer positive control and anonymous-denial tests remain explicitly partial. Exact lockout and temporary-suspension timing are manual acceptance gates.
- Read-only inspection of the **installed 7.161.15 vendor template** confirmed `max-login-delay-incorrect-attempts`, `max-login-delay-millis`, `disable-remember-me`, `password-autocomplete-enabled`, both API-key flags, Basic enablement/hiding, and project anonymous access keys. This is schema evidence, not evidence that desired values are active.
- A read-only probe of the existing general-security endpoint confirmed the `hideUnauthorizedResources` boolean exists and is currently **false**. That control is not already compliant.
- Terraform formatting/schema validation passed (plugin socket required unsandboxed execution). Python offline tests: **27 passed**; `git diff --check` passed.

Licence activation, replacing factory credentials, admin-token bootstrap, live configuration writes, all runtime behaviour checks and full policy acceptance remain pending. The initial-admin account is not represented as disabled. `make verify` now fails closed on outstanding manual acceptance rather than labelling a three-resource check as full compliance.

Read-only deployment checker trial: the vendor template includes an intentional invalid-YAML import marker, now handled only when reading its defaults. The corrected parser was exercised against the installed template. The running lab has **no `access.config.latest.yml`**, so the checker correctly stops with a missing current-configuration error instead of inferring runtime compliance from defaults. Deployment writes are also gated on that service-generated file. No speculative empty import was created.

## Terragrunt migration (2026-09-29)

- Installed the official Terragrunt **1.1.6** Darwin ARM64 binary in ignored `.local/bin`, checked against the release SHA256SUMS (`fd590f6eebf85ae56293c9b5de8e12505f51d13e6c44cdf6aecef56e094472a0`). HCL pins this version.
- Terragrunt HCL formatting/validation and real Terraform schema validation through the engine launcher passed. No credentials are needed for these offline checks.
- **39 Python tests passed**, including six tests running the actual Terragrunt binary with inert Terraform/Python executables. They cover successful hook order, detailed plan exit status, no after-hooks after failed Terraform, preflight and after-hook failure propagation, and validation without security hooks. Additional tests cover token delivery, destruction guards and avoiding recursive hooks.
- Terragrunt 1.1 always uses a source cache. Tests confirm the generated backend retains the original absolute state path, existing state remains untouched, and private files/state are excluded from source copies.
- Initial cache initialization omitted the extra platform-specific provider hashes. The final configuration generates the committed lock file verbatim, disables copying a replacement back, and uses readonly lock-file initialization. Real validation confirmed **no changes** to the existing multi-platform lock file.
- Executed the real `credentials_and_api` before-hook using `terragrunt run --no-auto-init -- plan -input=false`: it failed clearly on the missing admin token, and Terragrunt explicitly did not run Terraform.
- `git diff --check` passed. No Artifactory apply, restart, import or state migration was performed. Live end-to-end acceptance remains pending licence activation, administrator-token bootstrap and the current Access configuration file.

The updated README includes the Terragrunt hook sequence, state/cache behaviour, failure recovery and the revised ASCII ownership diagram. A successful managed-subset apply remains distinct from the full manual security acceptance gate.
