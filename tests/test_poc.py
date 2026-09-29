"""Offline tests for failure handling and secret-safe orchestration, not server emulation."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

spec = importlib.util.spec_from_file_location('poc', Path(__file__).resolve().parents[1] / 'scripts/poc.py')
poc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(poc)


class TransportTests(unittest.TestCase):
    def test_http_error_does_not_expose_response_or_token(self):
        api = poc.API('secret-token')
        api.opener.open = Mock(side_effect=urllib.error.HTTPError('url', 403, 'Forbidden', {}, io.BytesIO(b'secret-response')))
        with self.assertRaises(poc.Failure) as caught:
            api.get(poc.GENERAL)
        self.assertNotIn('secret', str(caught.exception))
        self.assertIn('HTTP 403', str(caught.exception))

    def test_denial_allows_auth_failure_but_not_server_failure(self):
        api = poc.API()
        for status in (401, 403, 404):
            api.opener.open = Mock(side_effect=urllib.error.HTTPError('url', status, '', {}, io.BytesIO()))
            self.assertEqual(api.request('GET', '/artifact', anonymous=True, allowed=poc.DENIED)[0], status)
        api.opener.open = Mock(side_effect=urllib.error.HTTPError('url', 500, '', {}, io.BytesIO()))
        with self.assertRaises(poc.Failure):
            api.request('GET', '/artifact', anonymous=True, allowed=poc.DENIED)

    def test_anonymous_never_sends_token(self):
        api = poc.API('secret-token')
        response = Mock(status=200)
        response.read.return_value = b'OK'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        api.opener.open = Mock(return_value=response)
        api.request('GET', '/ping', anonymous=True)
        self.assertIsNone(api.opener.open.call_args.args[0].get_header('Authorization'))

    def test_no_redirect_or_remote_path(self):
        self.assertIsNone(poc.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://remote'))
        for path in ('https://remote', '//remote/path', '/https://remote'):
            with self.assertRaises(poc.Failure):
                poc.API('token').request('PUT', path, {})


class WorkflowTests(unittest.TestCase):
    def test_setup_preserves_existing_database_credentials(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(poc, 'ROOT', Path(directory)), patch.object(poc, 'LOCAL', Path(directory) / '.local'):
            poc.setup()
            first = (Path(directory) / '.env').read_text()
            poc.setup()
            self.assertEqual(first, (Path(directory) / '.env').read_text())
            self.assertEqual((Path(directory) / '.env').stat().st_mode & 0o777, 0o600)

    def test_missing_fields_are_not_treated_as_disabled(self):
        api = Mock()
        api.get.return_value = {}
        self.assertIn('anonymous_access', poc.differences(api, {'anonymous_access': False}))

    def test_boolean_type_mismatch_is_detected(self):
        api = Mock()
        api.get.side_effect = [{'anonAccessEnabled': 0}, {}, {}]
        self.assertIn('anonymous_access', poc.differences(api, {'anonymous_access': False}))

    def test_reset_requires_exact_confirmation(self):
        with patch.object(poc, 'run') as run:
            with self.assertRaises(poc.Failure):
                poc.reset('yes')
            run.assert_not_called()

    def test_partial_fixture_failure_cleans_up_only_created_objects(self):
        api = Mock()
        fixture = poc.Fixtures(api)
        # repo GET/PUT succeed, artifact PUT fails; only repository should be deleted.
        api.request.side_effect = [(404, b''), (200, b''), poc.Failure('API unavailable'), (200, b'')]
        with self.assertRaises(poc.Failure):
            fixture.__enter__()
        self.assertEqual(api.request.call_args.args, ('DELETE', '/artifactory/api/repositories/' + fixture.repo))

    def test_existing_fixture_is_not_overwritten_or_deleted(self):
        api = Mock()
        api.request.side_effect = poc.Failure('Expected 404, got 200')
        fixture = poc.Fixtures(api)
        with self.assertRaises(poc.Failure):
            fixture.__enter__()
        self.assertEqual(api.request.call_count, 1)

    def test_token_is_env_only_and_ambient_flags_removed(self):
        with patch.object(poc, 'credentials', return_value='secret'), patch.object(poc, 'run') as run, patch.dict(os.environ, {'TF_CLI_ARGS': '-auto-approve', 'TF_VAR_url': 'remote'}):
            poc.terraform('plan')
            args = run.call_args.args
            self.assertNotIn('secret', ' '.join(args[0]))
            self.assertEqual(args[3]['JFROG_ACCESS_TOKEN'], 'secret')
            self.assertNotIn('TF_CLI_ARGS', args[3])
            self.assertNotIn('TF_VAR_url', args[3])


if __name__ == '__main__':
    unittest.main()
