"""Slow fixture hardware verifies coalescing, boundaries and nonblocking enqueue."""
import fcntl,json,os,random,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_quick_backend as backend
class ScrollTests(unittest.TestCase):
 def test_composed_steps_preserve_boundary_reversals(self):
  rng=random.Random(83)
  for initial in (5,20,50,95,100):
   for _ in range(50):
    steps=[rng.choice((-5,5)) for _ in range(30)];pending={};expected=initial
    for delta in steps:
     pending=backend.compose_brightness(pending,delta);expected=min(100,max(5,expected+delta))
    actual=min(pending['high'],max(pending['low'],initial+pending['shift']))
    self.assertEqual(actual,expected)
 def test_one_worker_merges_requests_and_reads_devices_once(self):
  with tempfile.TemporaryDirectory() as name,patch.object(backend,'cache_root',return_value=Path(name)):
   workers=[];writes=[];value=[20]
   def discover():time.sleep(.15);return [{'name':'DP-1','provider':'ddc','value':value[0]}]
   def write(item,action,target):time.sleep(.12);writes.append(target);value[0]=target
   def spawn(argv,**kwargs):
    descriptor=os.dup(kwargs['pass_fds'][0])
    thread=threading.Thread(target=backend.brightness_step_worker,args=(descriptor,));workers.append(thread);thread.start()
   with patch.object(backend,'brightness',side_effect=discover) as read,patch.object(backend,'brightness_write',side_effect=write),patch.object(backend.subprocess,'Popen',side_effect=spawn):
    latencies=[]
    for _ in range(20):
     start=time.monotonic();backend.step('brightness',5);latencies.append(time.monotonic()-start);time.sleep(.005)
    # A later reversal must still reach 80%, rather than replaying an outdated queue.
    time.sleep(.45)
    for _ in range(4):backend.step('brightness',-5)
    for thread in workers:thread.join(4);self.assertFalse(thread.is_alive())
    self.assertEqual(value[0],80);self.assertEqual(read.call_count,1);self.assertEqual(len(workers),1)
    self.assertLessEqual(len(writes),4);self.assertLess(max(latencies),.1)
 def test_cached_snapshot_avoids_hardware_read_and_worker_releases_lock(self):
  with tempfile.TemporaryDirectory() as name,patch.object(backend,'cache_root',return_value=Path(name)):
   root=Path(name);backend.write_json(root/'brightness-snapshot.json',{'time':time.time(),'items':[{'name':'DP-1','provider':'ddc','value':50}]})
   backend.write_json(root/'brightness-pending.json',{'time':time.time(),'jobs':{'':backend.compose_brightness({},5)}})
   owned=(root/'brightness-worker.lock').open('w');fcntl.flock(owned,fcntl.LOCK_EX);descriptor=os.dup(owned.fileno());owned.close()
   with patch.object(backend,'brightness') as read,patch.object(backend,'brightness_write') as write:
    backend.brightness_step_worker(descriptor);read.assert_not_called();self.assertEqual(write.call_args.args[2],55)
   with (root/'brightness-worker.lock').open('w') as lock:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 def test_default_scroll_targets_all_and_explicit_output_stays_scoped(self):
  for output,expected in [(None,[('DP-1',100),('DP-2',45)]),('DP-2',[('DP-2',45)])]:
   with tempfile.TemporaryDirectory() as name,patch.object(backend,'cache_root',return_value=Path(name)):
    root=Path(name);items=[{'name':'DP-1','provider':'ddc','value':98},
                          {'name':'DP-2','provider':'gamma','value':40},
                          {'name':'DP-3','provider':None,'value':None}]
    backend.write_json(root/'brightness-snapshot.json',{'time':time.time(),'items':items})
    backend.write_json(root/'brightness-pending.json',{'time':time.time(),'jobs':{output or '':backend.compose_brightness({},5)}})
    owned=(root/'brightness-worker.lock').open('w');descriptor=os.dup(owned.fileno());owned.close()
    writes=[]
    with patch.object(backend,'brightness_write',side_effect=lambda i,a,v:writes.append((i['name'],v))):
     backend.brightness_step_worker(descriptor)
    self.assertEqual(writes,expected)
 def test_bulk_slider_continues_after_one_display_fails(self):
  items=[{'name':'DP-1','provider':'ddc','value':20},{'name':'DP-2','provider':'gamma','value':50},
         {'name':'DP-3','provider':None,'value':None}]
  writes=[]
  def write(item,action,value):
   writes.append((item['name'],value))
   if item['name']=='DP-1':raise RuntimeError('device disconnected')
  with patch.object(backend,'brightness_write',side_effect=write):
   with self.assertRaisesRegex(RuntimeError,'DP-1'):backend.brightness_all(items,70)
  self.assertEqual(writes,[('DP-1',70),('DP-2',70)])
  self.assertEqual(items[1]['value'],70)
if __name__=='__main__':unittest.main()
