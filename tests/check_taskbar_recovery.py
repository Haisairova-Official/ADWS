"""Exercise pidfd recovery with a private dummy bar, never the user's Waybar."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='adws-recovery-check-') as name:
    temp = Path(name)
    source = temp / 'fixture.c'
    source.write_text('''#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
int main(void) {
 char pid[32]; snprintf(pid,sizeof(pid),"%d",getpid());
 if(fork()==0) { execlp("python3","python3",getenv("RECOVERY_RUNNER"),pid,NULL); _exit(1); }
 for(;;) pause();
}''')
    binary = temp / 'waybar'
    subprocess.run(['cc', str(source), '-o', str(binary)], check=True)
    runner = temp / 'runner.py'
    runner.write_text('''import os,sys,json
from pathlib import Path
sys.path.insert(0,os.environ['RECOVERY_TOOLS'])
import adws_taskbar_recover as r
os.setsid()
def start(config, style):
 Path(os.environ['RECOVERY_MARKER']).write_text(json.dumps([str(config),str(style)]))
 return True, 'isolated fixture'
r.start_taskbar=start
r.pids=lambda _: []
try: r.recover(int(sys.argv[1]))
finally: Path(os.environ['RECOVERY_DONE']).touch()
''')
    for limited in (False, True):
        state = temp / ('limited' if limited else 'recover')
        (state / 'adws').mkdir(parents=True)
        if limited:
            (state / 'adws/taskbar-recovery.json').write_text(json.dumps([time.time(), time.time()]))
        marker, done = state / 'started', state / 'done'
        env = {**os.environ, 'XDG_STATE_HOME':str(state), 'RECOVERY_RUNNER':str(runner),
               'RECOVERY_TOOLS':str(root/'tools'), 'RECOVERY_MARKER':str(marker), 'RECOVERY_DONE':str(done)}
        config, style = temp / 'config-bottom.jsonc', temp / 'style.css'
        p = subprocess.Popen([str(binary), '-c', str(config), '-s', str(style)], env=env)
        try:
            deadline = time.monotonic() + 8
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            assert done.exists(), 'Recovery helper did not finish'
            if limited:
                assert p.poll() is None and not marker.exists(), 'Rate limit failed'
            else:
                assert p.wait(timeout=2) == -15, 'Wrong process exit/signal'
                assert json.loads(marker.read_text()) == [str(config), str(style)]
                log = (state / 'adws/taskbar-recovery.log').read_text()
                assert '"restarted": true' in log and '"wchan"' in log
        finally:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=2)
print('Exact parent pidfd recovery, diagnostic log, preserved paths and restart limit passed.')
