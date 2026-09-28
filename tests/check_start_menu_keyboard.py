"""Run in Xvfb with a private DBus session; launches only a temporary fixture."""
from pathlib import Path
import os,subprocess,time,tempfile
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
    p=launch()
    subprocess.run(['xdotool','type','--clearmodifiers','Keyboard Fixture'],check=True);time.sleep(.4)
    subprocess.run(['xdotool','key','Return'],check=True)
    p.wait(timeout=5)
    for _ in range(30):
        if marker.exists():break
        time.sleep(.05)
    assert marker.exists(),'Enter did not launch the filtered .desktop application'
    p=launch();subprocess.run(['xdotool','key','Escape'],check=True);assert p.wait(timeout=5)==0
    print('Keyboard search/Enter launches only the fixture; Escape dismisses menu.')
