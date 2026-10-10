import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from adws_agenda import save_event, load_events, delete_event, validate_event

class AgendaTests(unittest.TestCase):
    def test_save_edit_delete_and_preserve_other_events(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'agenda.json'
            a=save_event({'date':'2026-10-08','title':'日程','time':'09:30','end':'10:00'},path)
            b=save_event({'date':'2026-10-08','title':'全天'},path)
            a['title']='更新';save_event(a,path)
            self.assertEqual(len(load_events(path)),2)
            self.assertEqual(load_events(path)[1]['title'],'更新')
            delete_event(a['id'],path)
            self.assertEqual(load_events(path),[b])
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
    def test_invalid_input_does_not_replace_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'agenda.json';path.write_text('corrupted')
            with self.assertRaises(ValueError):save_event({'date':'2026-10-08','title':'x'},path)
            self.assertEqual(path.read_text(),'corrupted')
        for changes in ({'date':'2026-02-30'},{'date':'20261008'},{'title':' '},{'time':'24:00'},{'time':'10:00','end':'09:00'},{'notes':'x'*2001}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                validate_event({'date':'2026-10-08','title':'x',**changes})
