import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from adws_sidebar import side_for_button
class SidebarPositionTests(unittest.TestCase):
    def test_front_back_buttons_follow_their_actual_location(self):
        self.assertEqual(side_for_button({'edge':'bottom','x':40},2000,'right'),'left')
        self.assertEqual(side_for_button({'edge':'top','x':1800},2000,'left'),'right')
    def test_vertical_bar_and_manual_launch(self):
        self.assertEqual(side_for_button({'edge':'left','x':1900},2000,'right'),'left')
        self.assertEqual(side_for_button({'edge':'right','x':10},2000,'left'),'right')
        self.assertEqual(side_for_button({},2000,'left'),'left')
