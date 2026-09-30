#!/usr/bin/env python3
"""Deployment configuration for the pinned local lab; never a compliance certificate."""
import argparse
import copy
import json
import subprocess
import sys
from urllib.parse import quote
import yaml
from poc import API, COMPOSE, Failure, LOCAL, credentials, private_write, run, setup, wait_ready

ETC = '/var/opt/jfrog/artifactory/etc'
SYSTEM = ETC + '/system.yaml'
LATEST = ETC + '/access/access.config.latest.yml'
TEMPLATE = ETC + '/access/access.config.template.yml'
IMPORT = ETC + '/access/access.config.import.yml'
# Deliberately disjoint from Terraform's anonymous-access, encryption and
# permanent-lock/expiry ownership. Basic lockdown needs approved identities/SSO.
ACCESS = {'security': {
    'allow-anonymous-in-projects': False,
    'authentication': {
        'disable-remember-me': True,
        'password-autocomplete-enabled': False,
        'disable-api-key-creation': True,
        'disable-api-key-authentication': True,
    },
    'user-lock-policy': {
        'max-login-delay-incorrect-attempts': 2,
        'max-login-delay-millis': 60000,
    },
}}
FRONTEND = {'frontend': {'featureToggler': {'accessPlatformAuditor': True}}}


def parse_yaml(text):
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError:
        raise Failure('Invalid server YAML; contents suppressed') from None
    if not isinstance(value, dict):
        raise Failure('Expected a YAML mapping; refusing to replace server configuration')
    return value


def merge(current, patch):
    """Preserve unrelated values; reject incompatible intermediate nodes."""
    result = copy.deepcopy(current)
    for key, value in patch.items():
        if isinstance(value, dict):
            node = result.get(key, {})
            if not isinstance(node, dict):
                raise Failure('Unexpected server configuration structure')
            result[key] = merge(node, value)
        else:
            result[key] = value
    return result


def mismatches(current, expected, prefix=''):
    result = []
    for key, value in expected.items():
        path = prefix + key
        actual = current.get(key) if isinstance(current, dict) else None
        if isinstance(value, dict):
            result.extend(mismatches(actual, value, path + '.'))
        elif type(actual) is not type(value) or actual != value:
            result.append(path)  # Never include potentially sensitive server values.
    return result


def read_server(path):
    try:
        return run([*COMPOSE, 'exec', '-T', 'artifactory', 'cat', path], capture=True).stdout
    except Failure:
        raise Failure('Server configuration unavailable: ' + path +
                      '; obtain the current service-generated configuration before proceeding') from None


def stage(path, text, must_be_absent=False):
    # Paths are constants, not user input. Values travel over stdin, never argv.
    guard = 'test ! -e "$1" || exit 8;' if must_be_absent else ''
    reference = SYSTEM if path == SYSTEM else LATEST
    command = guard + (' umask 077; test ! -e "$1.poc-tmp" && '
                       'cp -p "$2" "$1.poc-tmp" && chmod 600 "$1.poc-tmp" && '
                       'cat > "$1.poc-tmp" && mv "$1.poc-tmp" "$1"')
    result = subprocess.run([*COMPOSE, 'exec', '-T', 'artifactory', 'sh', '-c', command, 'poc', path, reference],
                            input=text, text=True, capture_output=True)
    if result.returncode:
        raise Failure('Failed to stage server configuration; inspect local backups before retrying')


def template_defaults(text):
    # The installed reference intentionally includes this non-YAML import guard.
    # Remove only that exact marker for reading defaults, never for deployment.
    lines = [line for line in text.splitlines()
             if line.split('#', 1)[0].strip() != 'do-not-import-this-file']
    return parse_yaml('\n'.join(lines))


def check_deployment():
    # latest.yml contains overrides; omitted keys use the installed vendor
    # template's defaults. Neither input is our local desired configuration.
    # A key missing from both files remains UNKNOWN.
    latest = parse_yaml(read_server(LATEST))
    actual = merge(template_defaults(read_server(TEMPLATE)), latest)
    failures = mismatches(actual, ACCESS)
    for path in failures:
        print('FAIL/UNKNOWN: ' + path)
    if failures:
        raise Failure('Access running-configuration read-back incomplete or differs from policy')
    print('PASS: Access service-generated settings match; suspension timing still requires live testing.')
    system = parse_yaml(read_server(SYSTEM))
    if mismatches(system, FRONTEND):
        raise Failure('Platform Auditor deployment flag missing; verify its UI activation after restart')
    print('CONFIGURED: Platform Auditor flag; verify role availability in the running UI.')
def deployment_preflight():
    """Read-only prerequisites, run before Terraform can modify anything."""
    # Parse both documents and verify merge compatibility before the apply.
    merge(parse_yaml(read_server(LATEST)), ACCESS)
    merge(parse_yaml(read_server(SYSTEM)), FRONTEND)
    run([*COMPOSE, 'exec', '-T', 'artifactory', 'test', '!', '-e', IMPORT], capture=True)
    for path in (SYSTEM, IMPORT):
        run([*COMPOSE, 'exec', '-T', 'artifactory', 'test', '!', '-e', path + '.poc-tmp'], capture=True)
    print('PASS: deployment source files and pending-file checks.')


def apply_deployment():
    setup()
    api = API(credentials())
    if api.get('/artifactory/api/system/version').get('version') != '7.161.15':
        raise Failure('Deployment automation is restricted to the pinned 7.161.15 lab')
    # Require administrator capability before any filesystem mutation.
    api.get('/artifactory/api/security/userLockPolicy')
    access_text, system_text = read_server(LATEST), read_server(SYSTEM)
    access, system = parse_yaml(access_text), parse_yaml(system_text)
    updated_access, updated_system = merge(access, ACCESS), merge(system, FRONTEND)
    # Refuse a pending import before any mutation, including the API patch.
    run([*COMPOSE, 'exec', '-T', 'artifactory', 'test', '!', '-e', IMPORT], capture=True)
    if updated_access == access and updated_system == system:
        print('No deployment changes required; verify runtime UI and behaviour separately.')
        return
    # Keep every backup; later retries must not overwrite pre-change evidence.
    import uuid
    backup = LOCAL / ('security-backup-' + uuid.uuid4().hex)
    backup.mkdir(mode=0o700)
    private_write(backup / 'access.yml', access_text)
    private_write(backup / 'system.yaml', system_text)
    stage(IMPORT, yaml.safe_dump(updated_access), must_be_absent=True)
    stage(SYSTEM, yaml.safe_dump(updated_system))
    run([*COMPOSE, 'restart', 'artifactory'])
    wait_ready()
    check_deployment()
    print('Deployment subset applied. Run make verify for outstanding acceptance gates.')


def check_inputs():
    path = LOCAL / 'security-inputs.json'
    if not path.exists():
        raise Failure('Copy config/security-inputs.example.json to .local/security-inputs.json; inputs are TBD')
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        raise Failure('Cannot read security inputs; contents suppressed') from None
    fields = {'approved_basic_auth_accounts', 'initial_admin_account', 'login_dialog_title',
              'login_dialog_text', 'internal_role_design_reference'}
    if not isinstance(data, dict) or set(data) != fields:
        raise Failure('Security input keys must match the example exactly')
    accounts = data['approved_basic_auth_accounts']
    if not isinstance(accounts, list) or not accounts or any(
            not isinstance(a, str) or not a.strip() or a != a.strip() or '<' in a or '>' in a
            for a in accounts):
        raise Failure('Approved Basic-auth identities are required; no placeholders')
    if len({a.casefold() for a in accounts}) != len(accounts):
        raise Failure('Duplicate Basic-auth identities')
    for field in fields - {'approved_basic_auth_accounts'}:
        value = data[field]
        if not isinstance(value, str) or not value.strip() or value.strip().upper() == 'TBD':
            raise Failure(field + ' is required and still TBD')
    print('Inputs complete; this does not apply or approve them. Follow docs/coverage.md.')
    return data


def audit_assignments(api=None):
    """Read-only dependency inventory; absence is never permission to delete."""
    api = api or API(credentials())
    api.get('/artifactory/api/security/userLockPolicy')  # Require admin before trusting a 404.
    status, body = api.request('GET', '/artifactory/api/security/groups/readers?includeUsers=true',
                               allowed={200, 404})
    findings = []
    if status == 200:
        try:
            group = json.loads(body)
        except ValueError:
            raise Failure('Invalid readers group response') from None
        if not isinstance(group, dict) or not isinstance(group.get('userNames'), list):
            raise Failure('Cannot establish readers membership; deletion prohibited')
        findings.append('readers group exists; members=' + str(len(group['userNames'])))
        if group.get('autoJoin') is not False:
            findings.append('readers autoJoin enabled or unknown')
    permissions = api.get('/artifactory/api/v2/security/permissions')
    if not isinstance(permissions, list):
        raise Failure('Unknown permission-list schema; dependency audit incomplete')
    for item in permissions:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            raise Failure('Invalid permission-list entry')
        permission = api.get('/artifactory/api/v2/security/permissions/' + quote(item['name'], safe=''))
        if not isinstance(permission, dict):
            raise Failure('Invalid permission detail response')
        for scope in ('repo', 'build', 'releaseBundle'):
            section = permission.get(scope)
            if section is None:
                continue
            if not isinstance(section, dict) or not isinstance(section.get('actions'), dict):
                raise Failure('Unknown permission actions; dependency audit incomplete')
            actions = section['actions']
            for kind, name in (('groups', 'readers'), ('users', 'anonymous')):
                principals = actions.get(kind, {})
                if not isinstance(principals, dict):
                    raise Failure('Unknown permission principals; dependency audit incomplete')
                if name in principals:
                    findings.append(scope + ': forbidden ' + name + ' permission assignment')
    for finding in findings:
        print('FAIL: ' + finding)
    print('MANUAL: inspect project roles/members, IdP mappings and token scopes before readers removal.')
    if findings:
        raise Failure('Forbidden principal/group dependencies found; no objects were modified')
    print('PASS: legacy permission/group subset only; project/IdP audit is still required.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['apply', 'check', 'inputs', 'audit', 'preflight'])
    args = parser.parse_args()
    try:
        {'apply': apply_deployment, 'check': check_deployment, 'inputs': check_inputs, 'audit': audit_assignments, 'preflight': deployment_preflight}[args.command]()
    except (Failure, OSError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
