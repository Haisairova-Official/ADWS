"""Measure actual repeated map/unmap; verify cache refresh and clean exit."""
import json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='adws-warm-test-') as tmp:
 tmp=Path(tmp);config=tmp/'config';(config/'adws').mkdir(parents=True)
 (config/'adws/taskbar-layout.json').write_text(json.dumps({'options':{'window_animations':False}}))
 env={**os.environ,'XDG_CONFIG_HOME':str(config),'ADWS_MENU_TIMING':'1','GIO_USE_VFS':'local','GTK_USE_PORTAL':'0','LC_ALL':'C.UTF-8','LANGUAGE':'en'}
 command=[str(ROOT/'src/adws-start-menu/target/release/adws-start-menu'),'--root',str(ROOT)]
 def visible():
  return subprocess.run(['xdotool','search','--onlyvisible','--name','^Start menu$'],capture_output=True,text=True).returncode==0
 def wait(check):
  end=time.monotonic()+4
  while not check():
   assert time.monotonic()<end,'Window did not map/unmap'
   time.sleep(.005)
 with (tmp/'menu.log').open('w') as output:
  start=time.monotonic();process=subprocess.Popen(command,env=env,stdout=output,stderr=output)
  try:
   wait(visible);cold=(time.monotonic()-start)*1000
   subprocess.run(['xdotool','key','Escape'],check=True);wait(lambda:not visible());assert process.poll() is None
   times=[]
   for _ in range(6):
    start=time.monotonic();subprocess.run(command,env=env,check=True);wait(visible);times.append((time.monotonic()-start)*1000)
    subprocess.run(['xdotool','key','Escape'],check=True);wait(lambda:not visible());assert process.poll() is None
   # Config invalidation creates a fresh UI without duplicate windows or a stuck grab.
   subprocess.run(command+['--theme','xp'],env=env,check=True);wait(visible)
   subprocess.run(['xdotool','key','Escape'],check=True);wait(lambda:not visible())
   subprocess.run(command+['--theme','akiacg'],env=env,check=True);wait(visible)
   subprocess.run(['xdotool','key','Escape'],check=True);wait(lambda:not visible())
   subprocess.run(command+['--exit'],env=env,check=True);process.wait(timeout=3)
   logs=(tmp/'menu.log').read_text();assert 'cached menu reopened' in logs
   assert 'panicked' not in logs
   print('cold_map_ms='+str(round(cold,1))+' warm_map_ms='+str([round(t,1) for t in times]))
   print('PASS reuse, six reopen cycles, theme invalidation, Escape and explicit exit.')
  finally:
   if process.poll() is None:process.terminate();process.wait(timeout=3)
