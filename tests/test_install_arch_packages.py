import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_install_arch_packages as arch


class Response(io.BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.headers = {'Content-Length': str(len(content))}


class ArchPackageReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.db = self.folder/'system-db'; (self.db/'local').mkdir(parents=True)
        (self.db/'sync').mkdir(); (self.db/'sync/core.db').write_bytes(b'unchanged old database')
        self.conf = self.folder/'pacman.conf'; self.conf.write_text('fixture; never modified')
        self.effective = ('[options]\nRootDir = /\nDBPath = '+str(self.db)+'\n'
                          'SigLevel = PackageRequired\nSigLevel = DatabaseOptional\n'
                          '[core]\nUsage = All\nServer = https://mirror.invalid/private-token/core/os/x86_64?key=SECRET\n')
        self.calls = []; self.urls = []; self.signature = None
        self.preview = 'ADWS_PACKAGE\tlinux\t7.2.14.arch1-1\t168986327\tcore\nADWS_PACKAGE\tfcitx5\t5.1.18-1\t94300\tcore\n'
        self.returncode = 0; self.stderr = ''

    def runner(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[0] == 'pacman-conf':
            return subprocess.CompletedProcess(argv, 0, self.effective, '')
        self.assertIn('--print', argv)
        self.assertIn('-Su', argv)
        self.assertNotIn('-Syu', argv); self.assertNotIn('-Sy', argv)
        database = Path(argv[argv.index('--dbpath')+1])
        self.assertNotEqual(database, self.db)
        self.assertEqual((database/'local').resolve(), self.db/'local')
        self.assertEqual((database/'sync/core.db').read_bytes(), b'fresh repository data')
        self.assertEqual(argv[argv.index('--config')+1], str(self.conf))
        return subprocess.CompletedProcess(argv, self.returncode, self.preview, self.stderr)

    def opener(self, request, **kwargs):
        self.urls.append(request.full_url)
        if '.db.sig' in request.full_url:
            if self.signature is None: raise urllib.error.HTTPError(request.full_url, 404, 'absent', {}, None)
            return Response(self.signature)
        return Response(b'fresh repository data')

    def review(self, **kwargs):
        return arch.review(['fcitx5'], pacman_conf=self.conf, runner=self.runner, opener=self.opener, **kwargs)

    def test_readonly_preview_includes_entire_upgrade_and_requested_packages(self):
        result = self.review()
        self.assertEqual(result['status'], 'reviewed')
        self.assertEqual([p['name'] for p in result['resolved_packages']], ['linux', 'fcitx5'])
        self.assertEqual(result['total_download_bytes'], 169080627)
        self.assertEqual((self.db/'sync/core.db').read_bytes(), b'unchanged old database')
        self.assertEqual(self.conf.read_text(), 'fixture; never modified')
        self.assertNotIn('SECRET', json.dumps(result)); self.assertNotIn('private-token', json.dumps(result))
        self.assertTrue(self.urls[0].endswith('/core.db?key=SECRET'))
        temporary = Path(next(c[c.index('--dbpath')+1] for c in self.calls if c[0]=='pacman'))
        self.assertFalse(temporary.exists())
        self.assertTrue(result['execution_requires_confirmation'])
        self.assertTrue(arch.verify_sources(result, runner=self.runner))

    def test_source_configuration_changed_requires_new_review(self):
        result = self.review()
        self.effective += '\n# effective change\n'
        with self.assertRaisesRegex(ValueError, 'changed'): arch.verify_sources(result, runner=self.runner)

    def test_configuration_drift_during_download_is_not_reported_as_reviewed(self):
        def change_after_download(request, **kwargs):
            response = self.opener(request, **kwargs)
            self.effective += '\n# changed effective policy\n'
            return response
        result = arch.review(['fcitx5'], pacman_conf=self.conf, runner=self.runner, opener=change_after_download)
        self.assertEqual(result['status'], 'requires_interactive_review')
        self.assertFalse(result['resolved_packages'])

    def test_custom_repositories_and_their_existing_signature_override_are_not_dropped(self):
        self.effective += '[local-company]\nUsage = All\nSigLevel = DatabaseNever\nServer = https://company.invalid/private-token?token=SECRET\n'
        self.preview += 'ADWS_PACKAGE\tcompany-tool\t2.1-1\t3200\tlocal-company\n'
        result = self.review()
        self.assertEqual(result['status'], 'reviewed')
        self.assertEqual([row['name'] for row in result['repositories']], ['core', 'local-company'])
        self.assertEqual(result['repositories'][1]['database_signature'], 'disabled-by-existing-policy')
        self.assertEqual(result['resolved_packages'][-1]['name'], 'company-tool')
        self.assertNotIn('SECRET', json.dumps(result))

    def test_signed_database_is_not_silently_accepted_or_downgraded(self):
        self.signature = b'opaque signature'
        result = self.review()
        self.assertEqual(result['status'], 'requires_interactive_review')
        self.assertFalse(any(c[0]=='pacman' for c in self.calls))
        self.assertFalse(result['resolved_packages'])
        self.assertIn('native pacman', result['conflicts'][0]['message'])

    def test_required_database_policy_and_custom_transfer_are_preserved(self):
        self.effective = self.effective.replace('DatabaseOptional', 'DatabaseRequired')
        result = self.review()
        self.assertEqual(result['status'], 'requires_interactive_review'); self.assertFalse(self.urls)
        self.effective = self.effective.replace('DatabaseRequired', 'DatabaseOptional').replace('[core]', 'XferCommand = /custom-helper %u\n[core]')
        result = self.review()
        self.assertEqual(result['status'], 'requires_interactive_review'); self.assertFalse(self.urls)

    def test_database_never_policy_does_not_gain_signature_checks(self):
        self.effective = self.effective.replace('DatabaseOptional', 'DatabaseNever')
        result = self.review()
        self.assertEqual(result['status'], 'reviewed')
        self.assertEqual(len(self.urls), 1)
        self.assertEqual(result['repositories'][0]['database_signature'], 'disabled-by-existing-policy')

    def test_unavailable_signature_is_not_equated_with_unsigned_database(self):
        def denied(request, **kwargs):
            if '.db.sig' in request.full_url:
                raise urllib.error.HTTPError(request.full_url, 403, 'denied', {}, None)
            return self.opener(request, **kwargs)
        result = arch.review(['fcitx5'], pacman_conf=self.conf, runner=self.runner, opener=denied)
        self.assertEqual(result['status'], 'requires_interactive_review')
        self.assertFalse(any(c[0]=='pacman' for c in self.calls))

    def test_https_redirect_never_downgrades_or_adds_credentials(self):
        request = arch.urllib.request.Request('https://mirror.invalid/core.db')
        for url in ('http://mirror.invalid/core.db', 'file:///etc/passwd', 'https://token:secret@mirror.invalid/core.db'):
            with self.assertRaises(ValueError): arch._NoDowngrade().redirect_request(request, None, 302, '', {}, url)

    def test_repository_failure_keeps_error_private_and_requires_review(self):
        self.returncode = 1
        self.stderr = 'conflict; mirror https://token:SECRET@example.invalid/private-token/pkg failed'
        result = self.review()
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('SECRET', json.dumps(result)); self.assertNotIn('private-token', json.dumps(result))
        self.assertIn('conflict', result['conflicts'][0]['message'])

    def test_transaction_diagnostics(self):
        for expected, line in (
            ('package-conflict', ':: a-2 与 a-patched-1 有冲突'),
            ('dependency', ":: installing core (2) breaks dependency 'core=1' required by plugin"),
            ('file-conflict', 'addon: /etc/example exists in filesystem'),
            ('missing-target', 'error: target not found: example'),
            ('transaction-failed', 'error: could not lock database'),
        ):
            with self.subTest(expected):
                issue = arch.transaction_issue(line)
                self.assertEqual(issue['kind'], expected)
                self.assertIn(line, issue['message'])

    def test_size_timeout_and_malformed_output_are_bounded(self):
        result = self.review(max_database_bytes=2)
        self.assertEqual(result['status'], 'requires_interactive_review')
        self.assertFalse(any(c[0]=='pacman' for c in self.calls))
        self.preview = 'ADWS_PACKAGE\tfcitx5\t5.1\tunknown\tcore\n'
        self.assertEqual(self.review()['status'], 'requires_interactive_review')
        with patch.object(arch, '_fetch', side_effect=TimeoutError('fixture timeout')):
            self.assertEqual(self.review()['status'], 'requires_interactive_review')

    def test_actual_execution_is_full_upgrade_and_requires_confirmation(self):
        command = arch.execution_command(['fcitx5', 'fcitx5'])
        self.assertEqual(command, ['pacman', '--config', '/etc/pacman.conf', '-Syu', '--needed', '--', 'fcitx5'])
        for forbidden in ('--noconfirm', '--dbpath', '-Sy'): self.assertNotIn(forbidden, command)
        for bad in ('--noconfirm', '../pkg', 'x; rm', '-bad'):
            with self.assertRaises(ValueError): arch.execution_command([bad])


if __name__ == '__main__': unittest.main()
