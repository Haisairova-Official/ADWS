import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from adws_control_center import popup_geometry, ControlCenter

class PopupGeometryTests(unittest.TestCase):
    def test_all_edges_fit_small_outputs_and_bad_anchor_data(self):
        for width,height in ((1920,1080),(800,600),(360,640),(40,30),(1,1)):
            rect=SimpleNamespace(width=width,height=height)
            for edge in ('top','bottom','left','right','invalid'):
                for inset in (None,'bad',float('inf'),-20,55,10000):
                    x,y,w,h,_,_=popup_geometry(rect,440,780,{'edge':edge,'inset':inset,'x':None,'y':'bad'})
                    self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
                    self.assertGreaterEqual(w,1);self.assertGreaterEqual(h,1)
                    self.assertLessEqual(x+w,width);self.assertLessEqual(y+h,height)

    def test_size_allocation_retains_opening_monitor(self):
        rect=SimpleNamespace(x=0,y=0,width=1920,height=1080)
        first=Mock();first.get_geometry.return_value=rect
        second=Mock();second.get_geometry.return_value=SimpleNamespace(x=1920,y=0,width=1920,height=1080)
        display=Mock();display.get_n_monitors.return_value=2
        display.get_monitor.side_effect=lambda i:(first,second)[i]
        display.get_monitor_at_point.return_value=second
        display.get_default_seat.return_value.get_pointer.return_value.get_position.return_value=(None,2000,50)
        window=Mock(motion_source=0,layer=None,popup_monitor=first)
        window.get_display.return_value=display
        window.get_allocated_width.return_value=440;window.get_allocated_height.return_value=780
        ControlCenter.position(window,{'edge':'top'},resize=False)
        self.assertIs(window.popup_monitor,first)
        display.get_monitor_at_point.assert_not_called()
        # Explicit relocation can select the new output.
        ControlCenter.position(window,{'edge':'top','monitor':1})
        self.assertIs(window.popup_monitor,second)

if __name__=='__main__':unittest.main()
