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
