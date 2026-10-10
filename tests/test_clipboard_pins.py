import json,os,stat,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_clipboard as backend
import adws_clipboard_pins as pins

class ClipboardPinTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        env=patch.dict(os.environ,{'XDG_DATA_HOME':temp.name});env.start();self.addCleanup(env.stop)
    def test_binary_survives_wiped_history_and_copies_exactly(self):
        data=b'\x89PNG\r\n\x1a\n\x00binary'
        line=pins.store('42\t[[ binary data png ]]',data)
        with patch.object(backend,'entries',return_value=[]),patch.object(backend,'run',return_value=b'') as run:
            self.assertEqual(backend.list_records(),[line]);backend.copy_entry(line)
            run.assert_called_once_with(['wl-copy'],input=data)
        self.assertEqual(backend.preview_data(line),data)
        self.assertEqual(stat.S_IMODE(pins.root().stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE((pins.root()/pins.identity(line)/'content').stat().st_mode),0o600)
    def test_pin_order_dedup_and_reopen(self):
        first=pins.store('1\tfirst',b'first');second=pins.store('2\tsecond',b'second')
        self.assertEqual(pins.store('1\tfirst',b'first'),first)
        with patch.object(backend,'entries',return_value=['1\tfirst','2\tsecond','3\tother']):
            self.assertEqual(backend.list_records(),[second,first,'3\tother'])
        self.assertEqual(len(pins.records()),2)
    def test_unpin_restores_history_before_removing_saved_copy(self):
        line=pins.store('1\tlong text',b'complete text')
        with patch.object(backend,'entries',return_value=['2\tlong text']),patch.object(backend,'run',return_value=b'') as run:
            self.assertEqual(backend.toggle_pin(line),['2\tlong text'])
            run.assert_called_once_with(['cliphist','store'],input=b'complete text')
        self.assertEqual(pins.records(),[])
    def test_failed_unpin_keeps_copy(self):
        line=pins.store('1\ttext',b'text')
        with patch.object(backend,'run',side_effect=OSError('failed')):
            with self.assertRaises(OSError):backend.toggle_pin(line)
        self.assertEqual(pins.read(line),b'text')
    def test_delete_pin_also_removes_existing_history_duplicate(self):
        line=pins.store('1\ttext',b'text')
        with patch.object(backend,'entries',return_value=['1\ttext']),patch.object(backend,'run',return_value=b'') as run:
            backend.delete_entry(line);run.assert_called_once_with(['cliphist','delete'],input=b'1\ttext\n')
        self.assertFalse(pins.records())
    def test_invalid_identity_and_failed_commit_preserve_existing_records(self):
        line=pins.store('1\ttext',b'text')
        with self.assertRaises(ValueError):pins.remove('adws-pin:../../elsewhere\tx')
        with patch.object(Path,'rename',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):pins.store('2\tnew',b'new')
        self.assertEqual([item['line'] for item in pins.records()],[line])
        self.assertFalse(list(pins.root().glob('.pending-*')))
    def test_preview_limit_does_not_truncate_stored_content(self):
        line=pins.store('1\ttext',b'original content')
        with self.assertRaises(ValueError):backend.preview_data(line,limit=3)
        self.assertEqual(pins.read(line),b'original content')

if __name__=='__main__':unittest.main()
