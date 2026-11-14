import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_install_ui as ui
from adws_install_progress import measure, stages


class InstallProgressTests(unittest.TestCase):
    def test_slow_stage_estimate_does_not_report_completion(self):
        plan = stages({'system_upgrade': True})
        journal = {'steps': {'packages': {'status': 'running'}}}
        _, done, percent, eta = measure(plan, journal, 1200)
        self.assertEqual(done, 0)
        self.assertLess(percent, 100)
        self.assertEqual(eta, '估算中')
        journal['steps']['packages']['status'] = 'passed'
        self.assertEqual(measure(plan, journal, 0)[1], 1)

    def test_back_reopens_previous_answer_and_updates_branch(self):
        seen = []
        def read_first(old):
            seen.append(old)
            return 'kitty' if old is None else 'other'
        def second(_):
            raise ui.Back
        def wizard():
            app = ui._decision('app', read_first)
            if app == 'kitty':
                ui._decision('next', second)
            return app
        with patch.object(ui, '_screen', object()):
            self.assertEqual(ui.navigate(wizard), 'other')
        self.assertEqual(seen, [None, 'kitty'])

    def test_wrap_chinese_text_in_terminal_columns(self):
        rows = ui._wrap('Firefox 和中文目录', 8)
        self.assertEqual(''.join(rows).replace(' ', ''), 'Firefox和中文目录')
        self.assertTrue(all(ui._width(line) <= 8 for line in rows))
