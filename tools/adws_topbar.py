"""Portable top-bar defaults, fresh installs and a separate temporary preview."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import sys
import subprocess
import tempfile
from adws_i18n import tr as _tr,chinese
from adws_atomic import replace_files
from adws_waybar import folder,decode,css_string

ROOT=Path(__file__).resolve().parents[1]
BEGIN='// ==== ADWS top Waybar BEGIN ===='
END='// ==== ADWS top Waybar END ===='

def profile_path():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'adws/waybar-top.json'

def rendered(root=ROOT,preview=False):
    data=decode((root/'config/waybar/config-top.jsonc').read_text(encoding='utf-8'))
    zh=chinese()
    def command(tab=None):return shlex.join(['bash',str(root/'adws'),'config',*(['--tab',tab] if tab else [])])
    def helper(name,*args):return shlex.join([sys.executable,str(root/'tools'/name),*args])
    native_start=shlex.join(['bash',str(root/'adws'),'start-menu'])
    actions={
      'actions':('打开默认终端','Open default terminal',helper('adws_launcher.py','--terminal')),
      'settings':('ADWS 设置','ADWS settings',command()),
      'screenshot':('截图','Take a screenshot','niri msg action screenshot'),
      'wallpapers':('壁纸设置','Wallpaper settings',command('wallpaper')),
      'colorpicker':('取色','Pick a color',helper('adws_color_picker.py')),
      'applauncher':('开始','Start','fuzzel' if shutil.which('fuzzel') else native_start),
      'updates':('系统更新 · 右键配置','System update · right-click to configure',helper('adws_topbar_update.py')),
      'adws-brightness':('亮度与夜间模式','Brightness and night mode',helper('adws_quick_controls.py','brightness','--panel')),
      'wlogout':('关机','Shut down',helper('adws_topbar_controls.py','poweroff')),
      'clipboard':('剪贴板历史','Clipboard history',helper('adws_clipboard.py')),
      'reboot':('重启','Restart',helper('adws_topbar_controls.py','reboot')),
      'logout':('注销','Log out',helper('adws_topbar_controls.py','logout')),
      'lockscreen':('锁屏','Lock',helper('adws_topbar_controls.py','lock')),
      'adws-brightness-low':('亮度 5%','Brightness 5%',helper('adws_topbar_controls.py','brightness','--value','5')),
      'adws-brightness-medium':('亮度 65%','Brightness 65%',helper('adws_topbar_controls.py','brightness','--value','65')),
      'adws-brightness-high':('亮度 100%','Brightness 100%',helper('adws_topbar_controls.py','brightness','--value','100')),
      'adws-night':('切换夜间模式','Toggle night mode',helper('adws_topbar_controls.py','night')),
      'taskbar-toggle':('显示／隐藏底部任务栏','Show/hide bottom taskbar',helper('adws_topbar_controls.py','toggle')),
    }
    for name,(cn,en,action) in actions.items():
        data['custom/'+name]['on-click']=action
        data['custom/'+name]['tooltip-format']=cn if zh else en
    data['idle_inhibitor']['tooltip-format-activated']='保持唤醒：禁止自动熄屏 · 单击允许 · 右键设置' if zh else 'Keep awake: block automatic screen blanking · click to allow · right-click for settings'
    data['idle_inhibitor']['tooltip-format-deactivated']='允许自动熄屏（按系统策略）· 单击保持唤醒 · 右键设置' if zh else 'Allow automatic screen blanking (system policy) · click to keep awake · right-click for settings'
    data['idle_inhibitor']['on-click-right']=command('power')
    data['custom/colorpicker']['tooltip-format']='左键：提取颜色\n右键：打开主题／壁纸选择器\n中键：切换系统配色方案' if zh else 'Left: pick a color\nRight: open theme/wallpaper selector\nMiddle: choose a system color scheme'
    data['custom/colorpicker']['on-click-right']=command('wallpaper')
    data['custom/colorpicker']['on-click-middle']=helper('adws_color_scheme.py')
    data['custom/taskbar-toggle']['exec']=helper('adws_topbar_controls.py','state')
    data['custom/cava']['exec']=helper('adws_cava.py')
    data['custom/cava']['on-click']='playerctl play-pause' if shutil.which('playerctl') else native_start
    data['custom/clipboard']['exec']=helper('adws_clipboard.py','--watch-start')
    data['custom/clipboard']['exec-on-event']=False
    data['custom/clipboard']['on-click-right']=helper('adws_clipboard.py')
    data['custom/adws-brightness']['on-scroll-up']=helper('adws_quick_controls.py','brightness','--step','5')
    data['custom/adws-brightness']['on-scroll-down']=helper('adws_quick_controls.py','brightness','--step','-5')
    data['custom/adws-brightness']['on-click-right']=helper('adws_quick_controls.py','brightness','--panel')
    if list(Path('/sys/class/backlight').glob('*')):
        data['group/brightness']['modules'].insert(1,'backlight/slider')
    from adws_topbar_update import configure_module
    data['custom/updates']=configure_module(data['custom/updates'],'auto','',root)
    from adws_layout import distro_logo
    data['custom/applauncher']['format']=distro_logo()[1]
    data['custom/applauncher']['on-click-right']=helper('adws_launcher.py','--terminal')
    data['network']['on-click']=command('network')
    data['bluetooth']['on-click']=command('bluetooth')
    for module in ('pulseaudio','wireplumber'):
        data[module]['on-click']=helper('adws_quick_controls.py','sound')
        data[module]['on-click-right']=helper('adws_quick_controls.py','sound','--panel')
    if not shutil.which('powerprofilesctl'):data['modules-center'].remove('power-profiles-daemon')
    pulse_socket=Path(os.environ.get('XDG_RUNTIME_DIR') or '/run/user/'+str(os.getuid()))/'pulse/native'
    if not pulse_socket.exists() and not os.environ.get('PULSE_SERVER') and shutil.which('wpctl'):
        data['group/audio']['modules']=['wireplumber']
    def battery_device(path):
        try:return (path/'type').read_text(encoding='utf-8').strip()=='Battery'
        except OSError:return False
    if not any(battery_device(p) for p in Path('/sys/class/power_supply').glob('*')):
        data['modules-right'].remove('battery')
    if os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
        data['modules-left']=['hyprland/workspaces','custom/right_div#5','hyprland/window','custom/right_div#6']
        if shutil.which('grim') and shutil.which('slurp'):data['custom/screenshot']['on-click']='grim -g "$(slurp)"'
        else:data['modules-center'].remove('custom/screenshot')
    if preview:
        data.update(name='adws-top-preview',exclusive=False,**{'margin-top':48})
        data['custom/settings']['tooltip-format']='临时预览 · ADWS 设置' if zh else 'Temporary preview · ADWS settings'
        data['modules-right'].append('custom/adws-preview-close')
        data['custom/adws-preview-close']={'format':'×','tooltip-format':'关闭此预览，不影响原有 Waybar' if zh else 'Close this preview; keep the original Waybar','on-click':shlex.join([sys.executable,str(root/'tools/adws_topbar.py'),'--stop-preview'])}
    from adws_fonts import with_symbol_fallbacks
    css=with_symbol_fallbacks((root/'config/waybar/style-top.css').read_text(encoding='utf-8'))
    for side in ('left','right'):
        name='arrow-'+side+'-symbolic.svg'
        css=css.replace('url('+json.dumps(name)+')','url('+css_string(str(root/'config/waybar'/name))+')')
    return json.dumps(data,ensure_ascii=False,indent=2)+'\n',css

def install_defaults(root=ROOT):
    # A user's config/config.jsonc always wins. Do not repoint its symlinks.
    live=folder()
    if any((live/name).exists() or (live/name).is_symlink() for name in ('config','config.jsonc')):return False
    config,css=rendered(root)
    files={live/'config.jsonc':config.encode()}
    if not (live/'style.css').exists() and not (live/'style.css').is_symlink():files[live/'style.css']=css.encode()
    files[profile_path()]=(json.dumps({'config':str(live/'config.jsonc'),'style':str(live/'style.css'),'installed_default':True})+'\n').encode()
    replace_files(files);return True

def preview_path():
    return Path(os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir())/('adws-top-preview-'+str(os.getuid())+'.json')

def stop_preview():
    marker=preview_path()
    if not marker.is_file():return False
    try:
        record=json.loads(marker.read_text(encoding='utf-8'));proc=Path('/proc')/str(record['pid'])
        args=(proc/'cmdline').read_bytes().decode().split('\0')
        identity=(proc/'stat').read_text(encoding='utf-8').rsplit(')',1)[1].split()[19]
        if Path(args[0]).name=='waybar' and record['config'] in args and identity==record['start'] and proc.stat().st_uid==os.getuid():os.kill(record['pid'],signal.SIGTERM)
    except (OSError,ValueError,KeyError,IndexError):pass
    marker.unlink(missing_ok=True);return True

def preview(root=ROOT,preset="standard"):
    from adws_waybar_compat import resolve_waybar,compatibility_errors
    binary=resolve_waybar()
    if not binary:raise RuntimeError('\n'.join(compatibility_errors(shutil.which('waybar'))))
    stop_preview()
    directory=Path(tempfile.mkdtemp(prefix='adws-top-preview-'))
    from adws_waybar_presets import rendered as preset_rendered
    config,css=preset_rendered(preset,root,preview=True)
    (directory/'config.jsonc').write_text(config, encoding='utf-8');(directory/'style.css').write_text(css, encoding='utf-8')
    colors=folder()/'colors.css'
    shutil.copy2(colors if colors.is_file() else root/'config/waybar/colors.css',directory/'colors.css')
    log=directory/'waybar.log'
    with log.open('w') as stream:process=subprocess.Popen([binary,'-c',str(directory/'config.jsonc'),'-s',str(directory/'style.css')],stdout=stream,stderr=stream,start_new_session=True)
    import time
    time.sleep(.6)
    if process.poll() is not None:raise RuntimeError(_tr('Waybar 预览未能启动：%s') % log.read_text(encoding='utf-8')[-1800:])
    start=(Path('/proc')/str(process.pid)/'stat').read_text(encoding='utf-8').rsplit(')',1)[1].split()[19]
    replace_files({preview_path():(json.dumps({'pid':process.pid,'start':start,'config':str(directory/'config.jsonc'),'log':str(log)})+'\n').encode()})
    return directory

def add_autostart(path):
    """Only a fresh default profile may receive this opt-in startup block."""
    from adws_autostart import write_config
    text=Path(path).read_text(encoding='utf-8')
    # Keep existing Waybar startup commands, including included config fragments.
    def existing(file,seen):
        file=Path(file).resolve()
        if file in seen:return False
        if len(seen)>32:return True
        seen.add(file)
        try:source=file.read_text(encoding='utf-8')
        except OSError:return True
        from adws_layout import _strip_jsonc
        source=_strip_jsonc(source)
        for line in source.splitlines():
            try:args=shlex.split(line.rstrip(';'),comments=True)
            except ValueError:continue
            if args and args[0]=='spawn-at-startup' and any(Path(arg).name=='waybar' for arg in args[1:]):return True
            if args and args[0]=='include' and len(args)>1:
                child=Path(args[1]).expanduser()
                if existing(child if child.is_absolute() else file.parent/child,seen):return True
        return False
    if BEGIN in text or existing(path,set()):return False
    data=json.loads(profile_path().read_text(encoding='utf-8'))
    from adws_waybar_compat import resolve_waybar
    argv=[resolve_waybar() or 'waybar','-c',data['config'],'-s',data['style']]
    line='spawn-at-startup '+' '.join(json.dumps(v,ensure_ascii=False) for v in argv)
    write_config(Path(path),text.rstrip()+'\n\n'+BEGIN+'\n'+line+'\n'+END+'\n');return True

def offer_autostart():
    if not profile_path().is_file():return
    data=json.loads(profile_path().read_text(encoding='utf-8'))
    if not data.get('installed_default'):return
    from adws_launcher import ask
    try:
        answer=ask(_tr('是否让默认顶部 Waybar 随 Niri 自启？（Y/n/Ctrl+C）')).lower()
        if answer in ('','y','yes'):
            from adws_windows import config_path
            add_autostart(config_path())
    except (EOFError,KeyboardInterrupt):return

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--install-defaults',action='store_true');parser.add_argument('--preview',action='store_true');parser.add_argument('--stop-preview',action='store_true');parser.add_argument('--offer-autostart',action='store_true');args=parser.parse_args()
    if args.install_defaults:print(_tr('已安装通用顶部 Waybar 默认配置。') if install_defaults() else _tr('保留现有顶部 Waybar 配置。'))
    elif args.preview:print(preview())
    elif args.stop_preview:stop_preview()
    elif args.offer_autostart:offer_autostart()
    else:parser.print_help()
if __name__=='__main__':main()
