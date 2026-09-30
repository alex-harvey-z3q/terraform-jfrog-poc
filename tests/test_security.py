"""Safety and effective-readback tests; these do not emulate JFrog."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import security
from poc import Failure


class SecurityTests(unittest.TestCase):
    def test_merge_preserves_unrelated_security_and_database(self):
        before = {'security': {'token': {'secret': 'keep'}, 'user-lock-policy': {'attempts': 5}},
                  'database': {'url': 'keep'}}
        saved = copy.deepcopy(before)
        result = security.merge(before, security.ACCESS)
        self.assertEqual(before, saved)
        self.assertEqual(result['security']['user-lock-policy']['attempts'], 5)
        self.assertEqual(result['database'], before['database'])
        self.assertEqual(result['security']['token'], before['security']['token'])
        self.assertEqual(security.merge(result, security.ACCESS), result)

    def test_conflicting_yaml_structure_fails_closed(self):
        with self.assertRaises(Failure):
            security.merge({'security': None}, security.ACCESS)

    def test_missing_default_and_wrong_type_are_unknown(self):
        expected = {'security': {'enabled': False, 'attempts': 2}}
        self.assertEqual(len(security.mismatches({}, expected)), 2)
        self.assertEqual(len(security.mismatches({'security': {'enabled': 0, 'attempts': True}}, expected)), 2)

    def test_yaml_error_does_not_echo_server_secrets(self):
        with self.assertRaises(Failure) as caught:
            security.parse_yaml('secret: [sensitive')
        self.assertNotIn('sensitive', str(caught.exception))
        with self.assertRaises(Failure):
            security.parse_yaml('!!python/object:danger {}')

    def test_tbd_inputs_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(security, 'LOCAL', Path(directory)):
            with self.assertRaises(Failure):
                security.check_inputs()
            (Path(directory) / 'security-inputs.json').write_text(json.dumps({
                'approved_basic_auth_accounts': [], 'initial_admin_account': None,
                'login_dialog_title': None, 'login_dialog_text': None,
                'internal_role_design_reference': None}))
            with self.assertRaises(Failure):
                security.check_inputs()

    def test_template_does_not_own_terraform_controls_or_basic_exceptions(self):
        auth = security.ACCESS['security']['authentication']
        self.assertNotIn('basic-authentication-enabled', auth)
        self.assertNotIn('password-encryption', auth)
        self.assertNotIn('attempts', security.ACCESS['security']['user-lock-policy'])
        self.assertNotIn('anonymous-access-enabled', security.ACCESS['security'])

    def test_dependency_audit_never_deletes(self):
        api = Mock()
        api.request.return_value = (200, json.dumps({'userNames': ['sensitive-user'], 'autoJoin': True}).encode())
        api.get.side_effect = [{}, [{'name': 'permission'}], {'repo': {'actions': {'groups': {'readers': ['r']},
                                                                                     'users': {'anonymous': ['r']}}}}]
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            with self.assertRaises(Failure):
                security.audit_assignments(api)
        self.assertNotIn('sensitive-user', output.getvalue())
        self.assertIn('forbidden anonymous', output.getvalue())
        self.assertTrue(all(call.args[0] == 'GET' for call in api.request.call_args_list))

    def test_unknown_membership_blocks_audit(self):
        api = Mock()
        api.request.return_value = (200, b'{}')
        with self.assertRaises(Failure):
            security.audit_assignments(api)
        api.get.assert_called_once_with('/artifactory/api/security/userLockPolicy')

    def test_unknown_version_prevents_writes(self):
        api = Mock()
        api.get.return_value = {'version': 'other'}
        with patch.object(security, 'setup'), patch.object(security, 'credentials', return_value='token'), \
             patch.object(security, 'API', return_value=api), patch.object(security, 'stage') as stage:
            with self.assertRaises(Failure):
                security.apply_deployment()
            stage.assert_not_called()

    def test_terraform_resource_hiding_adapter_reads_and_remediates(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            state, curl = directory / 'state', directory / 'curl'
            state.write_text('false')
            curl.write_text('#!/bin/sh\n'
                            'if [ "$1" = "--fail" ] && [ "$4" = "--request" ]; then\n'
                            '  printf true > "$TEST_STATE"\n'
                            '  exit 0\n'
                            'fi\n'
                            'printf "{\\\"hideUnauthorizedResources\\\": %s}" "$(cat \"$TEST_STATE\")"\n')
            curl.chmod(0o755)
            env = {**os.environ, 'PATH': str(directory) + os.pathsep + os.environ['PATH'],
                   'TEST_STATE': str(state), 'JFROG_URL': 'http://localhost:8082',
                   'JFROG_ACCESS_TOKEN': 'private-token'}
            read = subprocess.run([str(root / 'scripts/read-resource-hiding.sh')], input='{}', text=True,
                                  capture_output=True, env=env, check=True)
            self.assertEqual(read.stdout, '{"value":"false"}\n')
            applied = subprocess.run([str(root / 'scripts/set-resource-hiding.sh')], text=True,
                                     capture_output=True, env=env)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual(state.read_text(), 'true')
            self.assertNotIn('private-token', read.stdout + read.stderr + applied.stdout + applied.stderr)

    def test_terraform_resource_hiding_adapter_rejects_unknown_schema(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            curl = directory / 'curl'
            curl.write_text('#!/bin/sh\nprintf "{}"\n')
            curl.chmod(0o755)
            env = {**os.environ, 'PATH': str(directory) + os.pathsep + os.environ['PATH'],
                   'JFROG_URL': 'http://localhost:8082', 'JFROG_ACCESS_TOKEN': 'private-token'}
            result = subprocess.run([str(root / 'scripts/read-resource-hiding.sh')], input='{}', text=True,
                                    capture_output=True, env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('private-token', result.stdout + result.stderr)

    def test_staging_uses_stdin_and_preserves_service_file_ownership(self):
        with patch.object(security.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            security.stage(security.IMPORT, 'secret-value', must_be_absent=True)
        self.assertNotIn('secret-value', ' '.join(run.call_args.args[0]))
        self.assertEqual(run.call_args.kwargs['input'], 'secret-value')
        self.assertIn('cp -p', run.call_args.args[0][-4])
        self.assertEqual(run.call_args.args[0][-1], security.LATEST)

    def test_full_verify_cannot_certify_manual_controls(self):
        import poc
        with patch.object(poc, 'verify_managed'), patch.object(security, 'check_deployment'), \
             patch.object(security, 'audit_assignments'), patch.object(security, 'check_inputs'):
            with self.assertRaisesRegex(Failure, 'manual checks'):
                poc.verify()

    def test_bearer_positive_control_failure_prevents_denial_claim(self):
        import poc
        api = Mock()
        api.request.return_value = (200, b'wrong-content')
        fixture = poc.Fixtures(api)
        with self.assertRaises(Failure):
            fixture.behaviour()
        self.assertEqual(api.request.call_count, 1)

    def test_template_guard_is_only_removed_for_default_inspection(self):
        reference = 'security:\n  enabled: false\n  do-not-import-this-file # vendor guard\n'
        self.assertEqual(security.template_defaults(reference), {'security': {'enabled': False}})
        with self.assertRaises(Failure):
            security.parse_yaml(reference)

    def test_existing_import_prevents_all_writes(self):
        api = Mock()
        api.get.return_value = {'version': '7.161.15'}
        with patch.object(security, 'setup'), patch.object(security, 'credentials', return_value='token'), \
             patch.object(security, 'API', return_value=api), patch.object(security, 'read_server', return_value='{}'), \
             patch.object(security, 'run', side_effect=Failure('pending import')), patch.object(security, 'stage') as stage:
            with self.assertRaises(Failure):
                security.apply_deployment()
            stage.assert_not_called()


if __name__ == '__main__':
    unittest.main()
