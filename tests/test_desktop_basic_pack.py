import importlib.util
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('basic_engine',ROOT/'plugins/desktop-basic-pack/engine.py');engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
import adws_plugin as plugin
from adws_components import components

class BasicPackTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.root=Path(self.folder.name);self.now=[1000.]
    def make(self,kind,settings=None,name=None):return engine.Engine(kind,settings or {},self.root/((name or kind)+'.json'),lambda:self.now[0],random.Random(12))
    def test_merge_once_per_move_and_directions(self):
        self.assertEqual(engine.collapse([2,2,2,2]),([4,4,0,0],8))
        self.assertEqual(engine.collapse([2,2,4,0]),([4,4,0,0],4))
        board=[2,2,0,0]+[0]*12
        self.assertEqual(engine.move_board(board,'right'),([0,0,0,4]+[0]*12,4))
        board=[2,0,0,0,2,0,0,0]+[0]*8
        self.assertEqual(engine.move_board(board,'down'),([0]*12+[4,0,0,0],4))
        self.assertFalse(engine.available_moves([2,4,2,4,4,2,4,2,2,4,2,4,4,2,4,2]))
    def test_2048_undo_best_and_restore(self):
        e=self.make('game2048');e.state['board']=[2,2,0,0]+[0]*12;old=e.state['board'][:]
        e.event({'action':'left'});self.assertEqual(e.state['score'],4);self.assertEqual(sum(v!=0 for v in e.state['board']),2)
        e.event({'action':'undo'});self.assertEqual(e.state['board'],old);self.assertEqual(e.state['score'],0);self.assertEqual(e.state['best'],4)
        self.assertEqual(self.make('game2048').state['board'],old)
        e.state['board']=[2,4,8,16]+[0]*12;e.state.pop('undo',None);e.event({'action':'left'});self.assertNotIn('undo',e.state)
    def test_sliding_puzzle_solvable_and_only_adjacent_moves(self):
        for seed in range(80):
            e=engine.Engine('puzzle',{},self.root/f'puzzle-{seed}.json',rng=random.Random(seed))
            self.assertEqual(sorted(e.state['board']),list(range(16)))
            self.assertTrue(engine.puzzle_solvable(e.state['board']))
            self.assertNotEqual(e.state['board'],list(range(16)))
            blank=e.state['board'].index(15);before=e.state['board'][:]
            distant=next(i for i in range(16) if i!=blank and i not in engine.puzzle_neighbors(blank))
            e.event({'action':f'tile_{distant}'});self.assertEqual(e.state['board'],before)
            target=engine.puzzle_neighbors(blank)[0];e.event({'action':f'tile_{target}'})
            self.assertEqual(e.state['board'].index(15),target);self.assertEqual(e.state['moves'],1)
            self.assertTrue(engine.puzzle_solvable(e.state['board']))
        e=self.make('puzzle');e.state['board']=list(range(16));e.state['board'][14:]=[15,14]
        e.event({'action':'preview'});e.event({'action':'tile_15'});self.assertEqual(e.state['board'][-2:],[15,14])
        e.event({'action':'preview'});e.event({'action':'tile_15'})
        self.assertEqual(e.state['board'],list(range(16)))
        self.assertEqual(self.make('puzzle').state['board'],list(range(16)))
        # Old swap-game saves keep the chosen picture but start a legal game.
        e.state.pop('rules');e.state['image']=engine.ASSET;e.save()
        restored=self.make('puzzle');self.assertEqual(restored.state['image'],engine.ASSET)
        self.assertEqual(restored.state['rules'],'sliding-v1');self.assertTrue(engine.puzzle_solvable(restored.state['board']))

    def test_clock_faces_timezone_and_seconds(self):
        from adws_desktop_interactive import validate_view
        from adws_clock_face import hand_positions
        e=self.make('clock',{'display':'analog','face':'minimal','timezone':'Asia/Shanghai','second_hand':False})
        view=e.render()['view'];validate_view(view);dial=view['children'][0]
        self.assertEqual(dial['utc_offset'],28800);self.assertFalse(dial['seconds']);self.assertEqual(dial['face'],'minimal')
        for style in ('retro','minimal','railway','orbit'):
            a=hand_positions(10.3,face=style)[2];b=hand_positions(10.8,face=style)[2]
            if style in ('retro','railway'):self.assertAlmostEqual(a,b)
            else:self.assertGreater(b,a)
        self.assertNotEqual(hand_positions(10.01,face='retro')[2],hand_positions(10.15,face='retro')[2])
        self.assertEqual(e.render(),e.render()) # no per-frame IPC output
        e=self.make('clock',{'seconds':False,'timezone':'UTC'})
        self.assertEqual(e.render()['view']['children'][1]['text'],'00:16')
        bad=dict(dial,utc_offset=10**12)
        with self.assertRaises(ValueError):validate_view(bad)

    def test_clock_catalog_has_one_add_entry_preserves_legacy(self):
        import adws_desktop_widgets_model as model
        with patch('adws_layout.scan_available_plugins',return_value=[{'ok':True,'file':'x','manifest':{'id':engine.PACKAGE+'.clock','name':'时钟'}}]):
            items=model.catalog()
        self.assertEqual(len([d for d in items if d['name']=='时钟' and d.get('selectable',True)]),1)
        self.assertTrue(any(d['key']=='builtin:clock' for d in items))
        with patch('adws_layout.scan_available_plugins',return_value=[]):
            self.assertTrue(next(d for d in model.catalog() if d['key']=='builtin:clock').get('selectable',True))

    def test_timer_pause_resume_restart_and_alert_ack(self):
        e=self.make('timer',{'minutes':1});e.event({'action':'toggle'});self.now[0]+=10
        self.assertEqual(e.timer_value(),50);e.event({'action':'toggle'});self.now[0]+=10;self.assertEqual(e.timer_value(),50)
        e.event({'action':'toggle'});self.now[0]+=20;e=self.make('timer',{'minutes':1});self.assertEqual(e.timer_value(),30)
        self.now[0]+=31;payload=e.render();self.assertIsNotNone(payload['alert']);self.assertFalse(e.state['running'])
        e.event({'action':'alert_seen','value':payload['alert']['id']});self.assertIsNone(self.make('timer',{'minutes':1}).render()['alert'])
        e.event({'action':'reset'});self.assertEqual(e.timer_value(),60)
    def test_stopwatch_and_independent_notes(self):
        e=self.make('timer',{'mode':'stopwatch'});e.event({'action':'toggle'});self.now[0]+=7;e.event({'action':'toggle'});self.assertEqual(e.timer_value(),7)
        a=self.make('note',name='one');b=self.make('note',name='two');a.event({'action':'edit','value':'独立便签'*9000})
        self.assertEqual(len(a.state['text']),20000);self.assertEqual(b.state['text'],'');self.assertEqual(self.make('note',name='one').state['text'],a.state['text'])
    def test_photo_selection_and_bad_state(self):
        photo=self.make('photo');photo.event({'action':'image','value':engine.ASSET});self.assertEqual(photo.state['image'],engine.ASSET)
        photo.event({'action':'image','value':'https://example.com/a.png'});self.assertEqual(photo.state['image'],engine.ASSET)
        photo.event({'action':'default'});self.assertEqual(photo.state['image'],'')
        (self.root/'game2048.json').write_text('{bad');self.assertEqual(len(self.make('game2048').state['board']),16)
    def test_archive_six_repeatable_desktop_only_components(self):
        package=plugin.build_package(ROOT/'plugins/desktop-basic-pack',self.root/'basic.mplg')
        ok,errors,manifest=plugin.validate_package(package);self.assertTrue(ok,errors)
        self.assertEqual(manifest['id'],'org.AkiACG-Community.desktopBasicPack')
        self.assertEqual(components(manifest,'taskbar'),[])
        self.assertEqual(len(components(manifest,'desktop')),6)
        for component in components(manifest):self.assertFalse(component['isSingleOnly']);self.assertEqual(component['renderer'],'desktop.widgets-v1')
    def test_new_minutes_apply_to_paused_countdown(self):
        e=self.make('timer',{'minutes':1});self.assertEqual(e.timer_value(),60)
        e=self.make('timer',{'minutes':3});self.assertEqual(e.timer_value(),180)
        e.event({'action':'toggle'});e=self.make('timer',{'minutes':5});self.assertEqual(e.timer_value(),180)

    def test_bounded_ui_and_host_restriction(self):
        import gi;gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
        from adws_desktop_interactive import validate_view
        for kind in ('clock','timer','game2048','puzzle','photo','note'):validate_view(self.make(kind).render()['view'])
        for bad in ({}, {'id':'root','type':'column','children':[{'id':'root','type':'label'}]}, {'id':'root','type':'image','crop':[5,1,4,4]}, {'id':'root','type':'button','action':'rm -rf /'}):
            with self.assertRaises(ValueError):validate_view(bad)
        manifest={'id':'org.test.Pack','name':'Bad','version':'1.0.0','entry':'a.py','renderer':'desktop.widgets-v1','target':'taskbar'}
        self.assertTrue(plugin.validate_manifest(manifest))

if __name__=='__main__':unittest.main()
