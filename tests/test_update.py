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
