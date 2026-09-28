import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallSessionTests(unittest.TestCase):
    def environment(self, **updates):
        env = os.environ.copy()
        for key in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY", "DISPLAY",
                    "WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "LANGUAGE",
                    "ADWS_INSTALL_TRANSACTION"):
            env.pop(key, None)
        env.update(LC_ALL="C.UTF-8", **updates)
        return env

    def confirm(self, answer="", **env):
        return subprocess.run(
            ["bash", "-c", 'source "$1/scripts/adws-i18n.sh"; '
             'source "$1/scripts/adws-install-session.sh"; '
             'adws_confirm_install_session', "test", str(ROOT)],
            env=self.environment(**env), input=answer, text=True,
            capture_output=True, timeout=3,
        )

    def test_desktop_terminals_skip_confirmation(self):
        for display in ({"DISPLAY": ":0"}, {"WAYLAND_DISPLAY": "wayland-1"}):
            with self.subTest(display=display):
                result = self.confirm(**display)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_headless_defaults_to_cancel(self):
        for answer in ("", "\n", "n\n", "N\n"):
            with self.subTest(answer=answer):
                result = self.confirm(answer)
                self.assertEqual(result.returncode, 1)
                self.assertIn("Cancelled.", result.stdout)

    def test_ssh_and_tty_ask_even_with_display(self):
        for indicator in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY", "XDG_SESSION_TYPE"):
            with self.subTest(indicator=indicator):
                result = self.confirm("y\n", DISPLAY=":0", **{indicator: "tty"})
                self.assertEqual(result.returncode, 0)
                self.assertIn("are you serious?", result.stdout)

    def test_invalid_answer_retries(self):
        result = self.confirm("maybe\nY\n")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Enter y or n", result.stdout)

    def test_chinese(self):
        env = self.environment()
        env["LC_ALL"] = "zh_CN.UTF-8"
        result = subprocess.run(
            ["bash", str(ROOT / "install.sh")], env=env, input="n\n",
            text=True, capture_output=True, timeout=3,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("灵魂拷问：你是认真的吗？", result.stdout)
        self.assertIn("已取消。", result.stdout)

    def test_public_entries_cancel_before_python_or_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            binary = home / "bin"
            binary.mkdir()
            marker = home / "python-called"
            python = binary / "python3"
            python.write_text('#!/bin/sh\ntouch "$HOME/python-called"\nexit 99\n')
            python.chmod(0o755)
            env = self.environment(HOME=directory)
            env["PATH"] = str(binary) + os.pathsep + env["PATH"]
            for entry in (["install.sh"], ["adws", "install"], ["scripts/adws-install.sh"]):
                with self.subTest(entry=entry):
                    result = subprocess.run(
                        ["bash", str(ROOT / entry[0]), *entry[1:]],
                        env=env, input="\n", text=True, capture_output=True, timeout=3,
                    )
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertFalse(marker.exists())
                    self.assertFalse((home / ".config").exists())
                    self.assertFalse((home / ".local").exists())

    def test_install_help_remains_noninteractive(self):
        result = subprocess.run(
            ["bash", str(ROOT / "install.sh"), "--help"],
            env=self.environment(), input="", text=True, capture_output=True, timeout=3,
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("are you serious?", result.stdout)


if __name__ == "__main__":
    unittest.main()
