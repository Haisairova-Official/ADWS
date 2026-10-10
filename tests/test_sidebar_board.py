import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from adws_sidebar_model import normalize_board, placements, move_card, normalized_tasks, timer_remaining
import adws_sidebar  # Select GTK3 before importing the notification UI adapter.
from adws_sidebar_notifications import rows, snapshot, change, grouped


class BoardStateTests(unittest.TestCase):
    def test_empty_board_and_invalid_old_config(self):
        self.assertEqual(normalize_board({'order':[]})['order'],[])
        state=normalize_board({'order':['sound','bad','sound',{},'media'],'sizes':{'sound':True,'media':99}})
        self.assertEqual(state['order'],['sound','media'])
        self.assertEqual(state['sizes']['sound'],1)
        self.assertEqual(state['sizes']['media'],2)

    def test_resize_reflow_and_reordering_do_not_overlap(self):
        board=normalize_board({})
        for columns in (1,2):
            occupied=set()
            for _,x,y,span in placements(board,columns):
                for cell in range(x,x+span):
                    self.assertNotIn((cell,y),occupied);occupied.add((cell,y))
                    self.assertLess(cell,columns)
        self.assertEqual(move_card(board,'brightness','sound')[:2],['brightness','sound'])
        self.assertEqual(move_card(board,'sound','unknown'),board['order'])

    def test_task_validation_and_timer_survives_close(self):
        self.assertEqual(normalized_tasks([None,{'text':'  '},{'text':'task','done':1}]),[{'text':'task','done':False}])
        self.assertEqual(timer_remaining({'deadline':120},now=100),20)
        self.assertEqual(timer_remaining({'deadline':120},now=130),0)
        self.assertEqual(timer_remaining({'remaining':float('inf')}),1500)


class NotificationTests(unittest.TestCase):
    def test_grouping_preserves_every_notification_and_arrival_order(self):
        items=[{'id':i,'app':'Chat' if i%2 else 'Mail'} for i in range(60)]
        groups=grouped(items)
        self.assertEqual([name for name,_ in groups],['Mail','Chat'])
        self.assertEqual([item['id'] for item in groups[0][1]],list(range(0,60,2)))
        self.assertEqual(sum(len(group) for _,group in groups),60)
        self.assertEqual(len(grouped([{'app':' mail '},{'app':'MAIL'}])),1)
    def test_notifications_are_plain_text_and_bounded(self):
        result=rows([{'id':3,'summary':'<b>Hello</b> &amp; world','body':'x'*900,'app-name':'Test'}, {'id':-1}])
        self.assertEqual(result[0]['title'],'Hello & world')
        self.assertEqual(len(result[0]['body']),600)
        self.assertEqual(len(result),1)

    def test_mako_active_and_history_deduplicated(self):
        with patch('adws_sidebar_notifications.call',side_effect=[('mako',),([{'id':1,'summary':'current'}],),([{'id':1},{'id':2}],),(['default'],)]), patch('adws_sidebar_notifications.mako_dnd_mode',return_value=None):
            result=snapshot()
        self.assertEqual([item['id'] for item in result['items']],[1,2])
        self.assertFalse(result['items'][0]['historical'])
        self.assertTrue(result['items'][1]['historical'])
        self.assertIsNone(result['dnd'])

    def test_mako_dnd_preserves_unrelated_modes(self):
        with patch('adws_sidebar_notifications.call') as call, patch('adws_sidebar_notifications.snapshot',return_value={}):
            change({'provider':'mako','mode':'dnd','modes':['default','presentation']},'dnd')
        self.assertEqual(call.call_args.args[2].unpack(),(['default','presentation','dnd'],))
