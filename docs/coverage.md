# Basic Security Configuration coverage

This specification supersedes the original POC defaults. **No control is certified live compliant.** Anonymous access=false and lockout enabled/threshold=5 were already desired in Terraform, but had never been applied. The repository contains no Internal Role Design. Targets remain self-hosted Artifactory Pro **7.161.15** and `jfrog/artifactory` **12.11.13**. The organisation's edition, version, IdP and role design remain unknown.

## Ownership and acceptance matrix

| Requirement / scope | Implementation and present status | Effective verification / remaining work |
| --- | --- | --- |
| Anonymous access and `anonymous` user / Artifactory + projects | Terraform retains `enable_anonymous_access=false`; deployment adds Access `security.allow-anonymous-in-projects=false` | API read-back, seeded anonymous download denial; `security-audit` finds explicit anonymous permission assignments. Remove those and project memberships after review; do not try to delete the vendor principal. |
| Platform Auditor / platform UI | Deployment merges `frontend.featureToggler.accessPlatformAuditor=true` into existing `system.yaml` and restarts | File check is **configured**, not proof of activation. In User Management > Users, confirm Platform Auditor is available. If an auditor is assigned, verify read-only UI access. No arbitrary user is created. |
| Password encryption / Artifactory client credentials | Terraform changed `SUPPORTED` to `REQUIRED` | Read `passwordSettings.encryptionPolicy` via provider's read endpoint. This is JFrog encrypted-password handling, not TLS or at-rest encryption. |
| Basic disabled + hidden / Access and UI | **Manual, blocked on approved identities and tested external administration** | Follow authentication procedure below. No test enables Basic or adds an exception. |
| Initial administrator disabled / user lifecycle | **Manual, identity TBD** | Verify Disabled status and failed UI/API login after replacing its automation credentials. Disabling internal password or UI access alone does not disable the account. |
| SSH key authentication / Artifactory SSH server | **Manual; no verified resource/schema in pinned provider** | Keys Management > SSH Keys: uncheck Enable SSH Authentication. Reopen to verify, and test SSH authentication with an approved existing test key. No published SSH port in Compose is not proof of this setting. |
| API key authentication / Access | Deployment sets both `disable-api-key-authentication=true` and `disable-api-key-creation=true` | Read service configuration; test an existing valid test API key via header and Basic form is denied while a bearer token works. Creation being disabled alone is insufficient. No real keys are revoked automatically. |
| Remember Me / Access | Deployment sets `disable-remember-me=true` | Read service configuration and verify login checkbox is absent; test a fresh browser session. Existing cookies need separate session revocation/revalidation. |
| Password autocomplete / Access frontend | Deployment sets `password-autocomplete-enabled=false` | Key confirmed in the installed 7.161.15 vendor template; check service configuration and login form. Browser/password-manager behaviour requires testing too. |
| Custom Login Dialog every login / platform UI | **Manual mechanism; approved title/text TBD** in private inputs | General Management > Settings > Custom Login Dialog: Enabled, approved title/message. Verify acknowledgement before every new login, including logout/login and SSO paths. A general custom message is not equivalent. If this build suppresses repeat dialogs, escalate to JFrog; do not mark compliant. |
| 15-minute idle session timeout / authenticated UI session | **Blocked: reliable idle-timeout setting not established** | Obtain the supported idle-session control for the deployed build from JFrog. Configure 15 minutes there (and review IdP silent reauthentication). Verify a session idle for 15 minutes cannot perform authenticated actions without reauthentication; compare an active session. Do not substitute token lifetime, socket timeout, or `frontend.session.timeMinutes` (documented as token refresh interval). |
| 60-second suspension after 2 failures / Access | Deployment sets `max-login-delay-incorrect-attempts=2`, `max-login-delay-millis=60000` | Read-back plus timed test below. This is a **maximum delay setting**, not yet evidence that exactly 60 seconds starts at attempt two. |
| Permanent lockout after 5 failures / Access via legacy Artifactory API | Terraform retains enabled/5, now prevents other variable values | Exact boundary test below remains mandatory. Independent of suspension; deployment preserves permanent-lock/expiry fields. |
| Hide unauthorised resources / global Artifactory | Narrow YAML PATCH sets global `security.hideUnauthorizedResources=true`, checks API before and after | A non-admin bearer user without access must receive 404 for a known existing resource while an authorised bearer user gets its seeded bytes. Audit virtual repository overrides separately. |
| Predefined `readers` group absent / users, permissions, projects, IdP | **Deletion deliberately manual pending complete dependency inventory** | `security-audit` reads members/autojoin and repo/build/release-bundle permission references. Complete external/project checks below before deleting. No unconditional Terraform destroy or broad user detach. |
| No predefined global-role dependencies except Project Admin / project RBAC | **Blocked on Internal Role Design** | Audit all project members and group-derived assignments; migrate to approved custom roles. Keep vendor definitions. See role procedure below. |

Password expiry=false, inactive max age=90, notification=false are unchanged historical POC settings, not new organisational requirements.

## Automation and effective read-back

- `make verify-managed`: Terraform's three singleton policies, independent API read-back, and clean plan. Partial coverage only.
- `make apply` (also `make security-apply`): Terragrunt runs read-only preflight hooks, Terraform apply, then success-only Python deployment and verification hooks. Python applies local-only deployment configuration plus the narrow resource-hiding API patch. Requires an admin token and exact pinned server version. It merges existing YAML, preserves other fields, refuses pending imports, writes private backups, and restarts Artifactory. It does **not** disable Basic, disable administrators, delete groups, assign roles or invent banner wording.
- `make security-check`: compares Access's service-generated `access.config.latest.yml`, over the installed vendor template defaults, against managed settings; missing or wrongly typed keys fail. Also checks global hiding through the API. Platform Auditor still needs runtime UI verification.
- `make security-audit`: read-only legacy group and permission inventory; does not certify project/IdP dependencies. Unknown schema or membership fails; errors are not absence.
- `make verify`: executes the above checks and input validation, then **returns nonzero for required manual acceptance**. There is deliberately no local `compliant=true` switch. Signed operator evidence outside Git must cover every remaining matrix row.

Runtime source paths in this image: `/var/opt/jfrog/artifactory/etc/access/access.config.template.yml`, `access.config.latest.yml`, and `/var/opt/jfrog/artifactory/etc/system.yaml`. Template defaults are vendor supplied; neither the desired Python dictionary nor a local manifest is used as actual state. A successful YAML read does not prove UI behaviour. After every upgrade/restart, repeat runtime and behavioural verification. The vendor template contains an intentional non-YAML `do-not-import-this-file` marker; it is stripped only for reading defaults, never used as a deployment input. The current unactivated lab has no `access.config.latest.yml`: deployment/check commands stop until a current service-generated configuration is available. Obtain it through the supported JFrog configuration workflow; do not copy the template or fabricate an empty current configuration.

The adapter and Terraform share no desired fields. Terragrunt runs them serially: Terraform apply, Python deployment apply, then both read-backs. Import remains a separate initial step. Retest both after any change to catch cross-service conversion. Do not run concurrent configuration jobs. Legacy writes might affect related settings; drift in either subset is a failure.

Deployment updates are not transactional across the two files and HTTP patch. A failed restart/stage leaves a failed operation, not a pass or automatic weakening rollback. Retain `.local/security-backup-*` (contains secrets, 0700 directory/0600 files). Inspect pending import files and container health before retrying. To recover, restore the matching `system.yaml` and complete pre-change Access configuration as `access.config.import.yml`, with original service ownership, then restart. Recheck the separately patched hiding setting; recovery must never silently relax policy.

## Private inputs and Basic-auth transition

Copy `config/security-inputs.example.json` to `.local/security-inputs.json` (0600). `make security-inputs` validates shape and unresolved values, without displaying identities/text. These are **operator inputs, not JFrog API properties**:

| Input | Meaning |
| --- | --- |
| `approved_basic_auth_accounts` | Exact approved exception identities, including the approved break-glass account and any additional exceptions; empty is unresolved, not a wildcard. |
| `initial_admin_account` | Exact bootstrap identity to disable; never inferred from a placeholder. |
| `login_dialog_title`, `login_dialog_text` | Security-team-approved wording. Null in the example means TBD. |
| `internal_role_design_reference` | Location/version of approved role design; a reference alone does not implement it. |

Configure and test an external administrator through the IdP first; retain a working administrative bearer token belonging to an account that will remain enabled. In Security > General, set the Basic exceptions dropdown to **exactly** the approved accounts, disable Basic for internal users and hide it on the login page. Check saved settings and `security.authentication.basic-authentication-enabled=false` / `hide-basic-login=true` in current Access configuration. Test approved recovery login before disabling the identified initial administrator, revoke its outstanding credentials/sessions, and verify it cannot authenticate. An approved initial-admin exception must remain disabled, not usable as recovery.

Verify ordinary internal users are denied Basic with valid credentials, authorised exceptions work, and external administration still works. Under REQUIRED encryption, a plaintext-password denial alone proves neither Basic lockdown nor lockout: use the supported encrypted-password flow for approved test accounts. The hide setting retains a fallback link in JFrog; record this UI limitation and obtain policy clarification if hiding *all* entry points is required. Never disable the only functioning administrator to make a test pass.

## Timing and exact lockout acceptance

Use a separately approved disposable account through an authentication path where the server actually evaluates passwords (an approved Basic exception or the applicable IdP flow). Do not attack or lock the real break-glass account. Establish a successful login first, then reset its failure state.

Record timestamps and response status for two wrong-password attempts, respecting any delay after the first. During suspension, extra requests may be ignored and must not be counted as further failures. Test that correct credentials are blocked for the required 60 seconds after the second failure and recover afterwards without administrative unlock. Reset this test account before the permanent-lock test.

For permanent locking, space failed attempts beyond suspension windows (at least 61 seconds where applicable), avoid intervening successful logins, inspect the locked-users state after each attempt, and require lock **on the fifth evaluated failure**, not merely after a sixth. After waiting beyond temporary suspension, correct credentials must still fail until an administrator unlocks the test account. If configured 5 means lock on failure 6 in this build, record noncompliance and resolve the threshold mapping with JFrog before changing code; this repository does not silently reinterpret it. Test every node for HA and separately verify IdP-controlled password policy.

## Readers deletion and role migration

The group API and Terraform group resource support deletion, but neither establishes complete safe deletion. Before removal:

1. Run `make security-audit`; privately inventory all members and all repo/build/release-bundle permission targets referencing `readers`. An existing group fails the absence requirement even if autojoin is already false.
2. Inspect User Management > Groups and Permissions; check default/autojoin memberships, LDAP/SAML/OIDC/SCIM mappings, token group scopes, integrations, and group-derived permissions. In every Project, inspect Members and Roles. A clean legacy API inventory alone is insufficient.
3. Use Internal Role Design to migrate necessary access to approved custom groups/roles and update external provisioning so it cannot recreate/rejoin `readers`. Turn off autojoin while migrating; that is an interim measure, not acceptance.
4. After dependencies are removed and access tests pass, delete `readers` in User Management > Groups (or a reviewed import/destroy of only that group). Re-run the audit, confirm absence in the UI and authenticated group API, then provision a test user and verify no automatic `readers` membership/recreation.

For roles, use All Projects > User Management > Global Roles and each Project's Members/ Roles. Inventory direct and group-inherited assignments in every environment. Remove dependencies on every vendor predefined global role except **Project Admin** after replacing them with the approved design; do not merely rename a custom role or remove an empty definition. Include new vendor roles introduced on upgrades. No replacement design exists in this repository, so automatic reassignment would be speculative and potentially destructive. Platform Auditor is a separate platform user capability, not a predefined project global role; its explicit requirement remains applicable.

## Product boundaries and sources

- [Pinned general-security provider](https://github.com/jfrog/terraform-provider-artifactory/blob/v12.11.13/pkg/artifactory/resource/configuration/resource_artifactory_general_security.go): only anonymous access/encryption are exposed here. The provider's general read endpoint is not a stable public contract; fail on missing fields.
- [Security configuration](https://docs.jfrog.com/administration/docs/security-configuration): Basic transition, global resource hiding, and independent suspension/locking controls. Login suspension is node-specific in HA.
- [Platform Auditor](https://jfrog.com/help/r/jfrog-platform-administration-documentation/the-platform-auditor): available from 7.125.3; enabling the feature is distinct from assigning a user and cannot be combined with other user roles.
- [Access configurations](https://docs.jfrog.com/installation/docs/supported-access-configurations), [configuration files](https://docs.jfrog.com/installation/docs/access-yaml-configuration-files), [import procedure](https://docs.jfrog.com/installation/docs/upload-the-access-yaml-file): configuration ownership and service-generated read-back. Additional autocomplete key confirmed directly in the pinned image's vendor template, 2026-09-29.
- [API keys](https://docs.jfrog.com/user-management/docs/api-key): creation and authentication have separate switches; key deprecation does not prove old keys are rejected.
- [SSH settings](https://docs.jfrog.com/administration/docs/security-keys-management): keys management is edition-dependent (documentation specifies Enterprise+); do not count an unavailable UI as a disabled server.
- [Login dialog](https://docs.jfrog.com/administration/docs/general-settings): use the login-specific acknowledgement dialog, not the custom page message.
- [System YAML](https://docs.jfrog.com/installation/docs/artifactory-system-yaml): frontend session refresh is not documented as inactivity timeout.
- [Global roles](https://docs.jfrog.com/projects/docs/global-and-project-role-types): custom global roles require 7.77+; predefined definitions cannot generally be deleted. [Role management](https://docs.jfrog.com/projects/docs/manage-global-roles).
- [Legacy API migration](https://docs.jfrog.com/integrations/docs/deprecated-jfrog-apis): the pinned lockout/expiry and audit APIs are deprecated. Their replacements have different payloads; do not swap paths blindly.

No SaaS compatibility is claimed. All new writes, behavioural checks, licence-dependent UI capabilities and actual rollout remain untested until local activation and administrator-token bootstrap are complete.

## Terragrunt execution boundary

`examples/local/terragrunt.hcl` pins Terragrunt 1.1.6 and defines Python before/after hooks. Plan/import run only credential/API preflight. Apply additionally checks deployment prerequisites before Terraform, then runs `security.py apply`, `poc.py verify-managed`, and `security.py check` in order, only after success. A hook failure returns a failed command but cannot undo prior Terraform writes. Audits, private-input validation and full manual acceptance remain explicit commands.

The source cache excludes private inputs and state. A generated local backend retains the original state path and resource addresses; after-apply verification uses the initialized cache without recursively invoking hooks. Outside hooks, the Python command wrapper delegates engine operations to Terragrunt. Provider coverage and manual controls are unchanged. See [Terragrunt hooks](https://docs.terragrunt.com/features/units/hooks/) and the README for command and recovery details.
