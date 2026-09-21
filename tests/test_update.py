from pathlib import Path
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import mnws_update as update
from mnws_i18n import message


class UpdateTests(unittest.TestCase):
    def test_weight_boundaries_in_each_language(self):
        for language, first, second in [('zh_CN.UTF-8', '未检测到更新。', '您是最新的！'), ('en_US.UTF-8', 'No updates found.', "You're up to date!")]:
            with patch.dict(os.environ, {'LC_ALL':language, 'LANGUAGE':''}):
                for value in (0, 0.79999):
                    self.assertEqual(message('updates.none', rng=Mock(random=Mock(return_value=value))), first)
                for value in (0.8, 0.99999):
                    self.assertEqual(message('updates.none', rng=Mock(random=Mock(return_value=value))), second)

    def test_version_order(self):
        self.assertEqual(update.version_key('v1.27-A'),update.version_key('1.27 A'))
        self.assertLess(update.version_key('1.27-A'),update.version_key('1.30 Release'))
        self.assertLess(update.version_key('1.30 Development'), update.version_key('1.30 Pre-release'))
        self.assertGreater(update.version_key('1.30 Development'), update.version_key('1.25 Released'))
        self.assertEqual(update.version_key('1.25 Released'), update.version_key('1.25 Release'))
        self.assertLess(update.version_key('1.25 Pre-release'), update.version_key('1.25 Release'))
        self.assertEqual(update.version_key('v1.25-pre-release'), update.version_key('1.25 Pre-release'))
        self.assertLess(update.version_key('v1.2'), update.version_key('1.25 Release'))
        self.assertLess(update.version_key('1.25 H'), update.version_key('1.25 Release'))
        self.assertLess(update.version_key('1.25 Release'), update.version_key('v1.3'))
        self.assertLess(update.version_key('1.25 Release'), update.version_key('v1.25.1'))

    def test_cn_proxy_first_falls_back_to_github(self):
        with patch.object(update, 'mainland_china', return_value=True), patch.object(update, 'current_version', return_value='1.25 Release'), patch.dict(os.environ, {'MNWS_GITHUB_PROXY':'https://gh-proxy.com/'}), patch.object(update, 'read_json', side_effect=[ValueError('proxy error'), {'tag_name':'v1.26'}]) as read:
            result = update.check_update()
            self.assertTrue(result['available'])
            self.assertEqual(read.call_args_list[0].args[0], 'https://gh-proxy.com/' + update.API)
            self.assertEqual(read.call_args_list[1].args[0], update.API)
            self.assertEqual(result['url'], 'https://github.com/Haisairova-Official/MNWS/releases/tag/v1.26')

    def test_region_failure_does_not_block_direct_check(self):
        with patch.object(update, 'read_json', side_effect=[OSError('offline geo'), {'tag_name':'v1.25'}]) as read, patch.object(update, 'current_version', return_value='1.25 Release'), patch.object(update, 'message', return_value='none'):
            result = update.check_update()
            self.assertEqual(result, {'available':False, 'text':'none', 'url':None})
            self.assertEqual(read.call_args_list[1].args[0], update.API)

    def test_failed_checks_never_report_no_updates(self):
        with patch.object(update, 'mainland_china', return_value=True), patch.object(update, 'message') as message_mock:
            for response in ({}, {'tag_name':'bad'}, {'tag_name':'v1.26','prerelease':True}):
                with patch.object(update, 'read_json', return_value=response):
                    with self.assertRaises(RuntimeError): update.check_update()
            message_mock.assert_not_called()

    def test_remote_release_links_cannot_redirect_to_another_site(self):
        with patch.object(update, 'mainland_china', return_value=False), patch.object(update, 'read_json', return_value={'tag_name':'v99.0','html_url':'https://example.invalid'}):
            self.assertTrue(update.check_update()['url'].startswith('https://github.com/Haisairova-Official/MNWS/releases/tag/'))

    def test_preview_includes_prereleases_and_chooses_highest_version(self):
        releases = [
            {'tag_name':'v1.27-A','prerelease':True},
            {'tag_name':'v9.0','draft':True},
            {'tag_name':'lyrics-1.1.0'},
            {'tag_name':'v1.27-C','prerelease':True},
            {'tag_name':'v1.25','name':'1.25 Released'}]
        with patch.object(update,'mainland_china',return_value=False), patch.object(update,'current_version',return_value='1.27-B'), patch.object(update,'read_json',return_value=releases) as read:
            result=update.check_update(preview=True)
            self.assertTrue(result['available'])
            self.assertTrue(result['url'].endswith('/v1.27-C'))
            read.assert_called_once_with(update.PREVIEW_API)
            releases.append({'tag_name':'v1.30','prerelease':False})
            self.assertTrue(update.check_update(preview=True)['url'].endswith('/v1.30'))

    def test_preview_no_downgrade_empty_and_invalid_responses(self):
        with patch.object(update,'mainland_china',return_value=False), patch.object(update,'current_version',return_value='1.27-C'), patch.object(update,'message',return_value='none') as message_mock:
            for releases in ([], [{'tag_name':'v1.27-C','prerelease':True}], [{'tag_name':'v1.25'}], [{'tag_name':'v9.0','draft':True}]):
                with patch.object(update,'read_json',return_value=releases):
                    self.assertFalse(update.check_update(preview=True)['available'])
            message_mock.reset_mock()
            for releases in ({'message':'rate limited'}, [None], [{}], [{'tag_name':'invalid'}]):
                with patch.object(update,'read_json',return_value=releases), self.assertRaises(RuntimeError):
                    update.check_update(preview=True)
            message_mock.assert_not_called()

    def test_preview_proxy_failure_and_pagination(self):
        old={'tag_name':'v1.25'}
        with patch.object(update,'mainland_china',return_value=True), patch.dict(os.environ,{'MNWS_GITHUB_PROXY':'https://gh-proxy.com/'}), patch.object(update,'current_version',return_value='1.27-C'), patch.object(update,'read_json',side_effect=[OSError('proxy unavailable'), [old]*100, [{'tag_name':'v1.27-D','prerelease':True}]]) as read:
            self.assertTrue(update.check_update(preview=True)['url'].endswith('/v1.27-D'))
            self.assertEqual([c.args[0] for c in read.call_args_list],[
                'https://gh-proxy.com/'+update.PREVIEW_API,update.PREVIEW_API,
                update.RELEASES_API+'?per_page=100&page=2'])
        with patch.object(update,'mainland_china',return_value=False), patch.object(update,'read_json',side_effect=[[old]*100,OSError('second page failed')]), patch.object(update,'message') as message_mock:
            with self.assertRaises(RuntimeError):update.check_update(preview=True)
            message_mock.assert_not_called()

    def test_cli_preview_selection_and_invalid_options(self):
        with patch.object(update,'check_update',return_value={'text':'none','url':None}) as check, patch('builtins.print'):
            self.assertEqual(update.main(['--preview']),0)
            check.assert_called_once_with(preview=True)
            check.reset_mock()
            self.assertEqual(update.main([]),0)
            check.assert_called_once_with(preview=False)
            check.reset_mock()
            with self.assertRaises(SystemExit):update.main(['--preview','--bad'])
            check.assert_not_called()

    def test_shell_dispatch_for_both_update_spellings(self):
        import tempfile, subprocess
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            python=Path(folder)/'python3'
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            python.chmod(0o755)
            for flag in ['-u','--update']:
                result=subprocess.run(['bash',str(root/'mnws'),flag,'--preview'],env={**os.environ,'PATH':folder+os.pathsep+os.environ['PATH']},capture_output=True,text=True,check=True)
                self.assertEqual(result.stdout.splitlines(),[str(root/'tools/mnws_update.py'),'--preview'])

    def test_install_requires_confirmation(self):
        result={'available':True,'text':'new','url':'https://github.com/release','release':{'tag_name':'v1.30'}}
        with patch.object(update,'check_update',return_value=result), patch.object(update,'install_update',return_value='installed') as install, patch('builtins.print'):
            with patch('builtins.input',return_value='n'):
                self.assertEqual(update.main([]),0)
                install.assert_not_called()
            with patch('builtins.input',side_effect=EOFError):
                self.assertEqual(update.main([]),0)
                install.assert_not_called()
            with patch('builtins.input',side_effect=['wrong','']):
                self.assertEqual(update.main(['--preview']),0)
                install.assert_called_once_with(result)
            install.reset_mock()
            with patch('builtins.input',return_value='Y'), patch.object(update,'install_update',side_effect=RuntimeError('failed')):
                self.assertEqual(update.main([]),1)

    def test_no_update_does_not_prompt_or_install(self):
        with patch.object(update,'check_update',return_value={'available':False,'text':'none','url':None}), patch('builtins.input') as ask, patch.object(update,'install_update') as install, patch('builtins.print'):
            self.assertEqual(update.main([]),0)
            ask.assert_not_called();install.assert_not_called()
