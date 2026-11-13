import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_desktop_groups_model as groups
from adws_monitor_identity import assign

class GroupsTests(unittest.TestCase):
    def test_monitor_identity_survives_port_change(self):
        a=assign([dict(name='DP-1',make='V',model='4K',serial='123')])[0]
        b=assign([dict(name='HDMI-A-2',make='V',model='4K',serial='123')])[0]
        self.assertEqual(a['monitor_id'],b['monitor_id'])
        self.assertEqual(b['selector'],'V 4K 123')

    def test_identical_displays_do_not_share_identity(self):
        values=assign([dict(name=n,make='V',model='4K',serial=None) for n in ('DP-1','DP-2')])
        self.assertNotEqual(values[0]['monitor_id'],values[1]['monitor_id'])
        self.assertTrue(all(v['identity_ambiguous'] for v in values))

    def test_migration_preserves_legacy_grid(self):
        with tempfile.TemporaryDirectory() as folder:
            data=groups.load(Path(folder)/'groups.json',folder,{'DP-1:0':{folder+'/a.txt':[2,3]}})
            self.assertEqual(data['groups'][0]['cells']['a.txt'],[2,3])
            groups.validate(data)

    def test_group_motion_and_resolution_do_not_change_grid(self):
        row=groups.new_group('/tmp');row['cells']={'a':[1,2]}
        groups.move(row,500,350,1920,1080)
        x,y,w,h=groups.geometry(row,800,600)
        self.assertGreaterEqual(x,0);self.assertLessEqual(x+w,800)
        self.assertLessEqual(y+h,600);self.assertEqual(row['cells'],{'a':[1,2]})

    def test_new_files_fill_free_cells_without_resorting(self):
        row=groups.new_group('/tmp');row['cells']={'b':[2,1]}
        cells=groups.grid(row,['a','b','c'])
        self.assertEqual(cells['b'],[2,1]);self.assertEqual(cells['a'],[0,0])
        groups.move_icon(row,'a',2,1)
        self.assertEqual(row['cells']['b'],[0,0])

    def test_malformed_geometry_rejected(self):
        row=groups.new_group('/tmp');row['x']=float('nan')
        with self.assertRaises(ValueError):groups.validate({'version':1,'groups':[row]})

    def test_explicit_arrangement_preserves_grid_after_refresh(self):
        row=groups.new_group('/tmp')
        row.update(columns=2,cells={'a':[1,8],'.hidden':[2,5]})
        groups.arrange_visible(row, ['c','b','a'])
        expected={'c':[0,0], 'b':[1,0], 'a':[0,1]}
        self.assertEqual(groups.grid(row,['a','b','c']),expected)
        self.assertEqual(row['cells']['.hidden'],[2,5])
        groups.move_icon(row,'c',1,3)
        self.assertEqual(groups.grid(row,['a','b','c'])['c'],[1,3])

if __name__=='__main__':unittest.main()
