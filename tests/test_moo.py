import io
from contextlib import redirect_stdout
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import mnws_runtime as runtime
from mnws_i18n import tr as _tr


class MooTests(unittest.TestCase):
    def output(self, args):
        output = io.StringIO()
        with redirect_stdout(output), patch.object(runtime, 'pids') as pids, patch.object(runtime.subprocess, 'Popen') as browser:
            self.assertEqual(runtime.main(args), 0)
        pids.assert_not_called()
        return output.getvalue(), browser

    def test_plain_and_invalid(self):
        self.assertEqual(self.output(['moo'])[0], _tr('这里应该有个彩蛋吗？\n'))
        for args in (['moo', 'moo'], ['moo', '--help'], ['moo', '-v', '-v'], ['moo', '-vx'], ['desktop', 'moo'], ['-v', 'moo', 'extra']):
            output, browser = self.output(args)
            self.assertEqual(output, _tr('不，不是这样用的。\n'))
            browser.assert_not_called()

    def test_both_orders_and_separate_final_steps(self):
        messages = ['这个程序需要这样的彩蛋吗？', '这个程序我真没打算加入彩蛋。',
                    '你真的有够无聊的。', '别玩了！做点更有意义的事去吧！', '我叫你停下。',
                    '好吧，好吧。如果我给你彩蛋，你会满意吗？']
        for count in (1, 2, 3, 4, 5, 6, 7, 8, 100):
            for args in (['moo', '-' + 'v' * count], ['-' + 'v' * count, 'moo']):
                output, browser = self.output(args)
                expected = _tr(messages[count - 1]) + '\n' if count <= 6 else '' if count == 7 else _tr('喜欢吗？') + '\n'
                self.assertEqual(output, expected)
                if count == 7:
                    browser.assert_called_once()
                    self.assertEqual(browser.call_args.args[0], ['xdg-open', 'https://www.bilibili.com/video/BV1GJ411x7h7'])
                else:
                    browser.assert_not_called()
