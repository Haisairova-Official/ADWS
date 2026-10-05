"""Run in Xvfb with a private DBus session; launches only a temporary fixture."""
from pathlib import Path
import os,subprocess,time,tempfile,shlex
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='adws-menu-keyboard-') as tmp:
    tmp=Path(tmp);apps=tmp/'applications';apps.mkdir();marker=tmp/'launched'
    (apps/'adws-test.desktop').write_text('[Desktop Entry]\nType=Application\nName=ADWS Keyboard Fixture\nExec=/usr/bin/touch '+str(marker)+'\nCategories=Utility;\n')
    env={**os.environ,'XDG_DATA_HOME':str(tmp),'XDG_DATA_DIRS':'/usr/local/share:/usr/share','GIO_USE_VFS':'local','GTK_USE_PORTAL':'0','LC_ALL':'C.UTF-8','LANGUAGE':'en'}
    command=[str(root/'src/adws-start-menu/target/release/adws-start-menu'),'--root',str(root)]
    def launch():
        p=subprocess.Popen(command,env=env)
        for _ in range(60):
            got=subprocess.run(['xdotool','search','--onlyvisible','--name','^Start menu$'],capture_output=True,text=True)
            if got.returncode==0: time.sleep(.3); return p
            if p.poll() is not None:raise AssertionError('Menu quit before mapping')
            time.sleep(.05)
        p.kill();raise AssertionError('No mapped menu')
    for theme in ('kde','aero','xp','akiacg'):
        command=[str(root/'src/adws-start-menu/target/release/adws-start-menu'),'--root',str(root),'--theme',theme,'--one-shot']
        marker.unlink(missing_ok=True)
        p=launch()
        subprocess.run(['xdotool','type','--clearmodifiers','Keyboard Fixture'],check=True);time.sleep(.4)
        subprocess.run(['xdotool','key','Down','Return'],check=True)
        p.wait(timeout=5)
        for _ in range(30):
            if marker.exists():break
            time.sleep(.05)
        assert marker.exists(),'Enter did not launch the filtered .desktop application'
        command_marker=tmp/'command with spaces'
        command_marker.unlink(missing_ok=True)
        p=launch()
        subprocess.run(['xdotool','type','--clearmodifiers','touch -- '+shlex.quote(str(command_marker))],check=True)
        time.sleep(.2);assert not command_marker.exists(),'Typing executed a command before Enter'
        subprocess.run(['xdotool','key','Return'],check=True);assert p.wait(timeout=5)==0
        for _ in range(30):
            if command_marker.exists():break
            time.sleep(.05)
        assert command_marker.exists(),'Direct Enter did not execute the typed command'
        p=launch();subprocess.run(['xdotool','key','Return'],check=True);time.sleep(.2);assert p.poll() is None
        subprocess.run(['xdotool','key','Escape'],check=True);assert p.wait(timeout=5)==0
        print(theme+': selection launches fixture; direct Enter runs command; typing/empty Enter do nothing; Escape dismisses.')
