"""Exercise the actual Terragrunt hooks with inert executables, never Artifactory."""
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import poc
import security

ROOT = Path(__file__).resolve().parents[1]
TG = shutil.which('terragrunt') or str(ROOT / '.local/bin/terragrunt')


class HookLogicTests(unittest.TestCase):
    def test_terragrunt_wrapper_removes_ambient_routing_and_uses_current_python(self):
        with patch.object(poc.shutil, 'which', return_value='/tools/terragrunt'), \
             patch.object(poc, 'run') as run, patch.object(poc, 'credentials', return_value='secret'), patch.dict(os.environ, {'TG_SOURCE': 'remote', 'TF_CLI_ARGS': '-destroy'}):
            poc.terragrunt('apply')
        args, _, _, env = run.call_args.args
        self.assertEqual(args, ['/tools/terragrunt', '--working-dir', str(poc.TF), 'run', '--', 'apply'])
        self.assertNotIn('TG_SOURCE', env)
        self.assertNotIn('TF_CLI_ARGS', env)
        self.assertEqual(env['POC_PYTHON'], sys.executable)

    def test_hook_verification_reuses_initialized_cache_without_recursion(self):
        with patch.dict(os.environ, {'TG_CTX_COMMAND': 'apply'}), \
             patch.object(poc, 'credentials', return_value='secret'), patch.object(poc, 'run') as run, \
             patch.object(poc, 'terragrunt') as terragrunt:
            poc.terraform('plan', '-detailed-exitcode')
        terragrunt.assert_not_called()
        self.assertEqual(run.call_args.args[0][1], '-chdir=' + str(Path.cwd()))

    def test_preflight_missing_configuration_never_writes(self):
        with patch.object(security, 'read_server', side_effect=poc.Failure('missing config')), \
             patch.object(security, 'stage') as stage, patch.object(security, 'apply_resource_hiding') as hiding:
            with self.assertRaises(poc.Failure):
                security.deployment_preflight()
        stage.assert_not_called()
        hiding.assert_not_called()

    def test_engine_supplies_token_only_in_environment(self):
        engine = runpy.run_path(str(ROOT / 'scripts/terraform-engine'))
        with patch.object(poc, 'credentials', return_value='private-token'), \
             patch.object(sys, 'argv', ['terraform-engine', 'apply']), patch.object(os, 'execvpe') as execute:
            engine['main']()
        binary, args, env = execute.call_args.args
        self.assertEqual(binary, 'terraform')
        self.assertEqual(args, ['terraform', 'apply'])
        self.assertEqual(env['JFROG_ACCESS_TOKEN'], 'private-token')
        self.assertNotIn('private-token', ' '.join(args))

    def test_engine_validation_does_not_require_credentials(self):
        engine = runpy.run_path(str(ROOT / 'scripts/terraform-engine'))
        with patch.object(poc, 'credentials') as credentials, \
             patch.object(sys, 'argv', ['terraform-engine', 'validate']), patch.object(os, 'execvpe'):
            engine['main']()
        credentials.assert_not_called()

    def test_engine_rejects_destroy_apply_mode(self):
        engine = runpy.run_path(str(ROOT / 'scripts/terraform-engine'))
        with patch.object(sys, 'argv', ['terraform-engine', 'apply', '-destroy']), patch.object(os, 'execvpe') as execute:
            with self.assertRaises(poc.Failure):
                engine['main']()
        execute.assert_not_called()


@unittest.skipUnless(Path(TG).is_file(), 'Terragrunt 1.1.6 required for hook integration tests')
class TerragruntHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='jfrog-hook-test-')
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.unit = root / 'examples/local'
        self.unit.mkdir(parents=True)
        shutil.copyfile(ROOT / 'examples/local/terragrunt.hcl', self.unit / 'terragrunt.hcl')
        (self.unit / 'main.tf').write_text('terraform { required_version = ">= 1.5" }\n')
        (self.unit / '.terraform.lock.hcl').write_text('# lock sentinel\n')
        (root / '.local').mkdir()
        (root / '.local/admin-token').write_text('must-not-be-copied')
        (root / '.env').write_text('must-not-be-copied')
        (self.unit / 'terraform.tfstate').write_text('existing-state-sentinel')
        self.events = root / 'events.jsonl'
        engine = root / 'fake-terraform'
        engine.write_text('#!' + sys.executable + '\n' + '''
import json, os, sys
args = sys.argv[1:]
if any(a in ('version', '-version', '--version') for a in args):
    print(json.dumps({'terraform_version': '1.15.6'}) if '-json' in args else 'Terraform v1.15.6')
    sys.exit(0)
with open(os.environ['HOOK_EVENTS'], 'a') as f:
    f.write(json.dumps('terraform:' + args[0]) + '\\n')
sys.exit(int(os.environ.get('ENGINE_EXIT', '0')))
''')
        engine.chmod(0o755)
        hook = root / 'fake-python'
        hook.write_text('#!' + sys.executable + '\n' + '''
import json, os, sys
from pathlib import Path
name = 'hook:' + Path(sys.argv[1]).name + ':' + sys.argv[2]
with open(os.environ['HOOK_EVENTS'], 'a') as f:
    f.write(json.dumps(name) + '\\n')
sys.exit(1 if name == os.environ.get('FAIL_HOOK') else 0)
''')
        hook.chmod(0o755)
        self.engine = engine
        self.env = os.environ.copy()
        for name in list(self.env):
            if name.startswith(('TG_', 'TERRAGRUNT_', 'TF_')):
                self.env.pop(name)
        self.env.update(POC_PYTHON=str(hook), HOOK_EVENTS=str(self.events), NO_COLOR='1')

    def invoke(self, command, **env):
        result = subprocess.run([TG, '--working-dir', str(self.unit), 'run',
                                 '--tf-path', str(self.engine), '--no-auto-init', '--', command],
                                env={**self.env, **env}, capture_output=True, text=True, timeout=30)
        events = [json.loads(s) for s in self.events.read_text().splitlines()] if self.events.exists() else []
        return result, events

    def test_successful_apply_orders_hooks_and_preserves_state_location(self):
        result, events = self.invoke('apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ['hook:poc.py:preflight', 'hook:security.py:preflight', 'terraform:apply',
                                  'hook:security.py:apply', 'hook:poc.py:verify-managed', 'hook:security.py:check'])
        backends = list((self.unit / '.terragrunt-cache').rglob('backend.tf'))
        self.assertEqual(len(backends), 1)
        self.assertIn(str(self.unit / 'terraform.tfstate'), backends[0].read_text())
        self.assertFalse(list((self.unit / '.terragrunt-cache').rglob('admin-token')))
        self.assertFalse(list((self.unit / '.terragrunt-cache').rglob('.env')))
        self.assertFalse(list((self.unit / '.terragrunt-cache').rglob('terraform.tfstate')))
        self.assertEqual((self.unit / 'terraform.tfstate').read_text(), 'existing-state-sentinel')
        self.assertEqual((backends[0].parent / '.terraform.lock.hcl').read_text(), '# lock sentinel\n')

    def test_plan_only_runs_read_only_preflight_and_preserves_detailed_exit_code(self):
        result, events = self.invoke('plan', ENGINE_EXIT='2')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(events, ['hook:poc.py:preflight', 'terraform:plan'])

    def test_failed_terraform_apply_never_runs_mutating_hook(self):
        result, events = self.invoke('apply', ENGINE_EXIT='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, ['hook:poc.py:preflight', 'hook:security.py:preflight', 'terraform:apply'])

    def test_failed_preflight_prevents_terraform_and_after_hooks(self):
        result, events = self.invoke('apply', FAIL_HOOK='hook:security.py:preflight')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, ['hook:poc.py:preflight', 'hook:security.py:preflight'])

    def test_failed_configuration_hook_stops_success_checks(self):
        result, events = self.invoke('apply', FAIL_HOOK='hook:security.py:apply')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, ['hook:poc.py:preflight', 'hook:security.py:preflight', 'terraform:apply',
                                  'hook:security.py:apply'])

    def test_validate_does_not_call_any_security_hook(self):
        result, events = self.invoke('validate')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ['terraform:validate'])


if __name__ == '__main__':
    unittest.main()
