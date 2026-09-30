#!/usr/bin/env python3
"""Local-only Artifactory POC orchestration; full verification also uses PyYAML."""
import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'
TF = ROOT / 'examples/local'
COMPOSE = ['docker', 'compose', '-f', str(ROOT / 'compose.yaml'), '-p', 'jfrog-security-poc']
URL = 'http://localhost:8082'
GENERAL = '/artifactory/api/securityconfig'
LOCK = '/artifactory/api/security/userLockPolicy'
EXPIRY = '/artifactory/api/security/configuration/passwordExpirationPolicy'
DENIED = {401, 403, 404}
IMPORTS = {
    'module.security.artifactory_general_security.baseline': 'security',
    'module.security.artifactory_user_lock_policy.baseline': 'security-poc-lockout',
    'module.security.artifactory_password_expiration_policy.baseline': 'security-poc-expiration',
}


class Failure(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward credentials or accept a login page as success.


def private_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)


class API:
    def __init__(self, token=None):
        self.token = token
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, method, path, body=None, basic=None, anonymous=False, allowed=None, content_type=None):
        if not path.startswith('/') or path.startswith('//') or '://' in path:
            raise Failure('API paths must be local absolute paths')
        headers = {}
        if not anonymous:
            if basic:
                value = base64.b64encode((':'.join(basic)).encode()).decode()
                headers['Authorization'] = 'Basic ' + value
            elif self.token:
                headers['Authorization'] = 'Bearer ' + self.token
            else:
                raise Failure('No token: complete make bootstrap first')
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        elif body is not None:
            headers['Content-Type'] = 'application/octet-stream'
        if content_type:
            headers['Content-Type'] = content_type
        req = urllib.request.Request(URL + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=15) as response:
                status, data = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, data = error.code, error.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise Failure(f'{method} {path}: connection failed ({type(error).__name__})') from None
        accepted = allowed if allowed is not None else range(200, 300)
        if status not in accepted:
            raise Failure(f'{method} {path}: HTTP {status}; check licence, credentials and API compatibility')
        return status, data

    def get(self, path):
        _, data = self.request('GET', path)
        try:
            result = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            raise Failure(f'{path}: expected JSON, not HTML or an empty response') from None
        return result


def credentials():
    token = os.environ.get('JFROG_ACCESS_TOKEN', '').strip()
    if not token and (LOCAL / 'admin-token').exists():
        token = (LOCAL / 'admin-token').read_text().strip()
    if not token:
        raise Failure('Activate the trial and run make bootstrap; no admin token is available')
    return token


def run(args, capture=False, allowed=(0,), env=None):
    result = subprocess.run(args, cwd=ROOT, env=env, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if result.returncode not in allowed:
        raise Failure(f'{args[0]} {args[1]} failed (exit {result.returncode})')
    return result


def terraform_environment(require_credentials=True):
    env = os.environ.copy()
    if require_credentials:
        env['JFROG_ACCESS_TOKEN'] = credentials()
    env['JFROG_URL'] = URL
    env['TF_IN_AUTOMATION'] = '1'
    # Do not let ambient TF_VAR/CLI flags redirect or auto-approve this lab workflow.
    for name in list(env):
        if name.startswith(('TF_CLI_ARGS', 'TF_VAR_')) or name in ('TF_DATA_DIR', 'TF_WORKSPACE'):
            env.pop(name)
    return env


def terraform(*args, capture=False, allowed=(0,)):
    """Reuse the initialized hook directory; standalone reads go through Terragrunt."""
    if os.environ.get('TG_CTX_COMMAND') == 'apply':
        # The after-apply hook is already in Terragrunt's initialized cache.
        # Read/plan directly here so verification cannot recursively run hooks.
        if not args or args[0] not in ('output', 'plan', 'show', 'state'):
            raise Failure('Only verification commands may call Terraform inside an apply hook')
        return run(['terraform', f'-chdir={Path.cwd()}', *args], capture, allowed, terraform_environment())
    return terragrunt(*args, capture=capture, allowed=allowed)


def terragrunt(*args, capture=False, allowed=(0,)):
    binary = shutil.which('terragrunt')
    if not binary and (LOCAL / 'bin/terragrunt').is_file():
        binary = str(LOCAL / 'bin/terragrunt')
    if not binary:
        raise Failure('Install Terragrunt 1.1.6 or put it in .local/bin/terragrunt')
    env = terraform_environment(require_credentials=bool(args) and args[0] in ('plan', 'apply', 'import', 'refresh'))
    # Keep this wrapper fixed to the lab, regardless of ambient TG overrides.
    for name in list(env):
        if name.startswith(('TG_', 'TERRAGRUNT_')):
            env.pop(name)
    env['POC_PYTHON'] = sys.executable
    return run([binary, '--working-dir', str(TF), 'run', '--', *args], capture, allowed, env)


def preflight():
    api = API(credentials())
    if api.get('/artifactory/api/system/version').get('version') != '7.161.15':
        raise Failure('This Terragrunt unit targets only the pinned 7.161.15 local lab')
    for path in (GENERAL, LOCK, EXPIRY):
        api.get(path)
    print('PASS: local version, credentials and configuration read APIs.')


def setup():
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    LOCAL.chmod(0o700)
    if not (ROOT / '.env').exists():
        private_write(ROOT / '.env', 'POSTGRES_PASSWORD=' + secrets.token_hex(24) + '\n')
    print('Local configuration ready; existing database password preserved.')


def wait_ready():
    deadline = time.monotonic() + 600
    api = API()
    while time.monotonic() < deadline:
        try:
            _, body = api.request('GET', '/artifactory/api/system/ping', anonymous=True)
            if body.strip() == b'OK':
                print('Artifactory API ready at ' + URL)
                return
        except Failure:
            pass
        time.sleep(5)
    raise Failure('Readiness timed out after 10 minutes. Inspect docker compose logs --tail=100 locally; logs may contain secrets.')


def bootstrap():
    print('At http://localhost:8082 complete initial setup: activate trial licence,\n'
          'replace the default admin password, and create an expiring admin access token.\n'
          'The token is stored only in .local/admin-token (mode 0600).')
    token = os.environ.get('JFROG_ACCESS_TOKEN') or getpass.getpass('Admin access token: ').strip()
    if not token:
        raise Failure('An admin token is required')
    api = API(token)
    # These privileged reads check compatibility as well as authentication.
    for path in (GENERAL, LOCK, EXPIRY):
        api.get(path)
    private_write(LOCAL / 'admin-token', token + '\n')
    print('Token accepted; all three configuration read endpoints are accessible.')


def import_settings():
    terragrunt('init', '-input=false')
    # No state yet is normal; do not suppress other state-list errors.
    state = TF / 'terraform.tfstate'
    existing = set(terraform('state', 'list', capture=True).stdout.splitlines()) if state.exists() else set()
    for address, identifier in IMPORTS.items():
        if address not in existing:
            terragrunt('import', '-input=false', address, identifier)
    print('All global settings are imported.')


def desired():
    return json.loads(terraform('output', '-json', 'baseline', capture=True).stdout)


def differences(api, baseline):
    general, lock, expiry = api.get(GENERAL), api.get(LOCK), api.get(EXPIRY)
    actual = {
        'anonymous_access': general.get('anonAccessEnabled'),
        'encryption_policy': general.get('passwordSettings', {}).get('encryptionPolicy'),
        'lockout_enabled': lock.get('enabled'),
        'login_attempts': lock.get('loginAttempts'),
        'expiration_enabled': expiry.get('enabled'),
        'password_max_age': expiry.get('passwordMaxAge'),
        'notification_email': expiry.get('notifyByEmail'),
    }
    return {key: {'expected': value, 'actual': actual.get(key)} for key, value in baseline.items()
            if type(actual.get(key)) is not type(value) or actual.get(key) != value}


def verify_managed():
    diff = differences(API(credentials()), desired())
    if diff:
        print(json.dumps(diff, indent=2))
        raise Failure('Configuration read-back differs from baseline')
    clean_plan()
    print('PASS: Terraform-managed subset only; full security acceptance is separate.')


def verify():
    verify_managed()
    # No local checklist or desired configuration can certify runtime compliance.
    from security import check_deployment, audit_assignments, check_inputs
    check_deployment()
    audit_assignments()
    check_inputs()
    raise Failure('Full acceptance still requires the manual checks in docs/coverage.md; '
                  'managed settings alone do not establish compliance')


def clean_plan():
    result = terraform('plan', '-input=false', '-detailed-exitcode', allowed=(0, 2))
    if result.returncode != 0:
        raise Failure('Expected a clean plan, but Terraform detected changes')


def drift():
    api = API(credentials())
    baseline = desired()
    policy = api.get(LOCK)
    policy['loginAttempts'] = baseline['login_attempts'] + 1
    api.request('PUT', LOCK, policy)
    if api.get(LOCK).get('loginAttempts') != baseline['login_attempts'] + 1:
        raise Failure('Drift injection did not persist')
    print('Changed only loginAttempts outside Terraform. Run make plan, then make apply.')


def apply(automatic=False):
    args = ['apply', '-input=false']
    if automatic:
        args.append('-auto-approve')
    else:
        # Interactive confirmation is Terraform's normal reviewed-plan workflow.
        args = ['apply']
    terragrunt(*args)


class Fixtures:
    def __init__(self, api):
        self.api = api
        suffix = uuid.uuid4().hex[:12]
        self.repo = 'poc-' + suffix
        self.description = 'Unmanaged sentinel ' + suffix
        self.content = b'Artifactory security POC test artifact\n'
        self.cleanup_paths = []

    def create(self, path, body):
        self.api.request('GET', path, allowed=(404,)) # Refuse to overwrite existing objects.
        self.api.request('PUT', path, body)
        self.cleanup_paths.append(path)

    def __enter__(self):
        try:
            self.create('/artifactory/api/repositories/' + self.repo,
                        {'rclass': 'local', 'packageType': 'generic', 'description': self.description})
            self.api.request('PUT', self.artifact, self.content)
            return self
        except Exception:
            self.__exit__(*sys.exc_info())
            raise

    @property
    def artifact(self):
        return '/artifactory/' + self.repo + '/fixture.txt'

    def sentinel(self):
        if self.api.get('/artifactory/api/repositories/' + self.repo).get('description') != self.description:
            raise Failure('Unmanaged repository description changed')

    def behaviour(self):
        # Positive control uses an existing bearer token. REQUIRED encryption and
        # disabled Basic mean password denials cannot establish account lockout.
        _, body = self.api.request('GET', self.artifact)
        if body != self.content:
            raise Failure('Bearer-token download did not return the seeded artifact')
        self.api.request('GET', self.artifact, anonymous=True, allowed=DENIED)
        print('PASS: bearer download and anonymous denial only; lockout/Basic checks remain manual.')

    def __exit__(self, *_):
        failures = []
        for path in reversed(self.cleanup_paths):
            try:
                self.api.request('DELETE', path, allowed={200, 202, 204, 404})
            except Failure as error:
                failures.append(str(error))
        if failures:
            raise Failure('Fixture cleanup incomplete: ' + '; '.join(failures))


def integration():
    verify_managed()
    with Fixtures(API(credentials())) as fixture:
        fixture.behaviour()
        fixture.sentinel()


def demo():
    verify_managed()
    with Fixtures(API(credentials())) as fixture:
        fixture.behaviour()
        try:
            drift()
            plan = LOCAL / 'drift.tfplan'
            result = terragrunt('plan', '-input=false', '-detailed-exitcode', '-out=' + str(plan), allowed=(0, 2))
            if result.returncode != 2:
                raise Failure('Terraform failed to detect injected drift')
            document = json.loads(terraform('show', '-json', str(plan), capture=True).stdout)
            changed = [r for r in document.get('resource_changes', []) if r['change']['actions'] != ['no-op']]
            if len(changed) != 1 or changed[0]['address'] != 'module.security.artifactory_user_lock_policy.baseline':
                raise Failure('Drift plan contained unexpected resource changes')
            change = changed[0]['change']
            delta = {k for k in change['before'] if change['before'][k] != change['after'].get(k)}
            if change['actions'] != ['update'] or delta != {'login_attempts'}:
                raise Failure('Drift plan did not contain exactly the lockout threshold update')
            terragrunt('apply', '-input=false', str(plan))
        finally:
            # The disposable lab must not be left with injected drift after a failed assertion.
            apply(automatic=True)
            (LOCAL / 'drift.tfplan').unlink(missing_ok=True)
        verify_managed()
        fixture.sentinel()
    print('PASS: drift detected precisely, remediated, and unrelated configuration preserved.')


def persistence():
    verify_managed()
    run([*COMPOSE, 'stop', 'artifactory'])
    run([*COMPOSE, 'restart', 'postgres'])
    run([*COMPOSE, 'up', '-d', '--wait', '--wait-timeout', '60', 'postgres'])
    run([*COMPOSE, 'start', 'artifactory'])
    wait_ready()
    verify_managed()


def reset(confirmation):
    if confirmation != 'delete-local-poc':
        raise Failure('Reset deletes only POC volumes/state. Use make reset CONFIRM=delete-local-poc')
    run([*COMPOSE, 'down', '--volumes'])
    for path in TF.glob('terraform.tfstate*'):
        path.unlink()
    for name in ('admin-token', 'drift.tfplan'):
        (LOCAL / name).unlink(missing_ok=True)
    print('Lab data/state removed. Repeat bootstrap and import after starting again.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['setup', 'wait', 'bootstrap', 'init', 'validate', 'preflight', 'import', 'plan', 'apply', 'verify', 'verify-managed', 'test', 'drift', 'demo', 'persistence', 'reset'])
    parser.add_argument('--confirm', default='')
    args = parser.parse_args()
    commands = {'setup': setup, 'wait': wait_ready, 'bootstrap': bootstrap, 'import': import_settings,
                'init': lambda: terragrunt('init', '-input=false'),
                'validate': lambda: terragrunt('validate'), 'preflight': preflight,
                'plan': lambda: terragrunt('plan', '-input=false'), 'apply': apply, 'verify': verify, 'verify-managed': verify_managed,
                'test': integration, 'drift': drift, 'demo': demo, 'persistence': persistence,
                'reset': lambda: reset(args.confirm)}
    try:
        commands[args.command]()
    except (Failure, ValueError, KeyError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Interrupted.', file=sys.stderr)
        return 130
    return 0


if __name__ == '__main__':
    # security imports this module; share the same Failure class in CLI mode.
    sys.modules['poc'] = sys.modules[__name__]
    sys.exit(main())
