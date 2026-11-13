"""GTK coverage of SDDM theme controls; all privileged operations use a fixture."""
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gtk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import adws_sddm
from adws_i18n import tr
from adws_sddm_page import SddmPage
from adws_settings_widgets import enhance_choices


class Host:
    def __init__(self):
        self.errors = []
        self.confirm = Mock(return_value=True)

    def run_worker(self, operation, success, failure):
        try:
            operation()
        except Exception as exc:
            self.errors.append(str(exc))
            failure()
        else:
            success()


def wait_for(condition):
    until = time.monotonic() + 4
    while time.monotonic() < until:
        while GLib.MainContext.default().iteration(False):
            pass
        if condition():
            return
        time.sleep(.01)
    raise AssertionError('Timeout waiting for SDDM page')


def state(manager='sddm', **values):
    return dict(dict(manager=manager, manager_name=manager.upper(), current='breeze',
                     themes=['breeze', 'arctic'], managed=False, can_apply=True,
                     can_restore=False, conflict=''), **values)


def main():
    host = Host()
    sample = state('gdm', can_apply=False)
    def inspect():
        return sample
    with patch.object(adws_sddm, 'inspect', side_effect=inspect), \
            patch.object(adws_sddm, 'apply') as apply, patch.object(adws_sddm, 'restore') as restore:
        window = Gtk.Window()
        page = SddmPage(host)
        window.add(page)
        enhance_choices(page, translate=tr)
        window.show_all()

        def ready():
            wait_for(lambda: page.snapshot == sample and page.refresh_button.get_sensitive())

        ready()
        assert page.manager_name.get_text() == 'GDM'
        assert not page.theme_card.get_visible()
        assert not page.apply_button.get_sensitive()
        apply.assert_not_called()
        sample = state()
        page.refresh_button.clicked()
        ready()
        assert page.theme_card.get_mapped()
        assert page.choices._adws_choice_button.get_mapped()
        assert page.choices._adws_choice_button.caption.get_text() == 'breeze'
        assert not page.restore_button.get_visible()

        page.choices.set_active_id('arctic')
        before = sample
        def takeover(*args):
            nonlocal sample
            sample = state(current='arctic', managed=True, can_restore=True)
            return {'backup': '/fixture/backup'}
        apply.side_effect = takeover
        page.apply_button.clicked()
        ready()
        apply.assert_called_once_with('arctic', before)
        assert '/fixture/backup' in page.result.get_text()
        assert page.restore_button.get_visible()
        assert not page.apply_button.get_sensitive()

        page.choices.set_active_id('breeze')
        apply.side_effect = adws_sddm.AuthorizationCancelled('cancel')
        page.apply_button.clicked()
        ready()
        assert page.choices.get_active_id() == 'breeze'
        assert page.apply_button.get_sensitive()
        assert page.result.get_text() == tr('已取消授权。')
        assert host.errors == []

        host.confirm.return_value = False
        page.restore_button.clicked()
        restore.assert_not_called()
        host.confirm.return_value = True
        restore.side_effect = PermissionError('authorization required')
        page.restore_button.clicked()
        ready()
        assert host.errors == ['authorization required']
        assert page.restore_button.get_sensitive()

        before = sample
        def release(snapshot):
            nonlocal sample
            sample = state()
            return {'backup': None}
        restore.side_effect = release
        page.restore_button.clicked()
        ready()
        restore.assert_called_with(before)
        assert not page.restore_button.get_visible()
        assert page.result.get_text() == tr('已恢复系统登录主题配置。')

        sample = state(conflict='/etc/sddm.conf', can_apply=False)
        page.refresh_button.clicked()
        ready()
        assert sample['conflict'] in page.management.get_text()
        assert not page.apply_button.get_sensitive()
        sample = state(current='', themes=[], can_apply=False)
        page.refresh_button.clicked()
        ready()
        assert page.current.get_text() == tr('当前主题：%s') % tr('SDDM 内置主题')
        assert not page.choices.get_sensitive()
        window.destroy()
    print('PASS: manager selection, takeover, rollback, conflicts, no themes, authorization and cancellation')


if __name__ == '__main__':
    main()
