# Configuration coverage

Implementation targets Artifactory Pro **7.161.15**, PostgreSQL **16.8**, and provider **12.11.13**. Resource schema and endpoint mappings were checked against the provider's tagged source. Read-only probes on the running server returned HTTP 200 and the expected fields for all three configuration endpoints. Live write compatibility is pending licence activation; these mappings are not a claim of end-to-end validated support.

| Control | Ownership | Read / write API | Acceptance |
| --- | --- | --- | --- |
| Anonymous access=false | `artifactory_general_security.baseline` | GET `/artifactory/api/securityconfig`; PATCH `/artifactory/api/system/configuration` | Read-back + anonymous artifact denied |
| Client-password encryption=SUPPORTED | Same resource | Same APIs | Read-back; not a TLS assertion |
| Lockout enabled; threshold=5 | `artifactory_user_lock_policy.baseline` | GET/PUT `/artifactory/api/security/userLockPolicy` | Read-back + disposable account appears in locked-users API |
| Password expiry=false; inactive max age=90; notify=false | `artifactory_password_expiration_policy.baseline` | GET/PUT `/artifactory/api/security/configuration/passwordExpirationPolicy` | Read-back |
| Basic authentication enabled | Verified only | Basic-authenticated download by synthetic reader | Success and exact artifact content |
| Repository description | Unmanaged sentinel | Repository configuration API | Unchanged across apply |
| SSO, LDAP, MFA, complexity, token tuning | Deferred | Not called | Out of scope |

All singleton settings are imported before apply. Provider changes are serialized because the settings may share global configuration. Terraform uses `prevent_destroy` on all three resources. Python is a verifier and deliberate drift injector, not a second baseline owner. No API fallback adapter is currently needed by the selected schemas; add one only after a demonstrated coverage gap, with its own check/apply contract and tests.

## Limitations and compatibility gate

The general-security resource uses an undocumented read endpoint and a YAML configuration patch; its documentation excludes SaaS. The provider's user-lock and password-expiry resources use legacy Artifactory security endpoints. JFrog's deprecation documentation describes newer Access APIs and different payloads, so a schema-valid Terraform module alone is insufficient evidence.

On an unsupported endpoint or failed write, stop and document the failure. Prefer upgrading/fixing the provider or a documented Access API adapter after verifying its exact schema and edition/version support. Do not translate fields blindly or send partial full-object replacements. The lab does not call browser-private endpoints directly to bypass a missing API.

The full Security → General UI has not yet been inventoried against the organisation's installation. This module intentionally represents the selected POC baseline, not the entire page.

## Source references

- [Pinned general security implementation](https://github.com/jfrog/terraform-provider-artifactory/blob/v12.11.13/pkg/artifactory/resource/configuration/resource_artifactory_general_security.go)
- [Pinned lockout implementation](https://github.com/jfrog/terraform-provider-artifactory/blob/v12.11.13/pkg/artifactory/resource/security/resource_artifactory_user_lock_policy.go)
- [Pinned expiration implementation](https://github.com/jfrog/terraform-provider-artifactory/blob/v12.11.13/pkg/artifactory/resource/security/resource_artifactory_password_expiration_policy.go)
- [API deprecation and migration guidance](https://docs.jfrog.com/integrations/docs/deprecated-jfrog-apis)
- [Docker installation](https://docs.jfrog.com/installation/docs/docker)

- [Artifactory PostgreSQL version support](https://docs.jfrog.com/installation/docs/artifactory-database-requirements)
- [Locked-users API used by the behavioural test](https://docs.jfrog.com/administration/reference/getlockedoutusers)
