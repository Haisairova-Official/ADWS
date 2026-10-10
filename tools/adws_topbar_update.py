"""Run an explicitly configured system upgrade in the user's default terminal."""
import argparse
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from adws_i18n import tr

MANAGERS=('auto','yay','paru','custom')

def resolve_command(manager='auto',custom=''):
    if manager not in MANAGERS:raise ValueError(tr('无效的更新程序'))
    if manager=='custom':
        if not custom.strip():raise ValueError(tr('请输入自定义更新命令'))
        return custom.strip()
    if manager=='auto':
        manager=next((name for name in ('yay','paru') if shutil.which(name)),None)
        if manager is None:raise RuntimeError(tr('未找到 yay 或 paru，请在 Waybar 设置中选择自定义更新命令。'))
    if not shutil.which(manager):raise RuntimeError(tr('未找到更新程序：%s') % manager)
    return shlex.join([manager,'-Syu'])

def terminal_command(command,terminal=None):
    if terminal is None:
        from adws_launcher import terminal_argv
        terminal=terminal_argv()
    terminal=list(terminal)
    name=Path(terminal[0]).name
    # Keep the upgrade result visible, including errors, without adding shell flags to the user's command.
    script=command+'\nstatus=$?\nprintf "\\n%s\\n" '+shlex.quote(tr('按回车关闭窗口。'))+'\nread -r answer\nexit "$status"'
    shell=['/bin/sh','-c',script]
    if name=='xdg-terminal-exec':return terminal+shell
    if name in ('gnome-terminal','kgx','ptyxis'):return terminal+['--']+shell
    if name=='wezterm':return terminal+['start','--']+shell
    if name=='xfce4-terminal':return terminal+['--execute']+shell
    return terminal+['-e']+shell

def module_settings(module):
    settings=module.get('adws-update',{})
    if not isinstance(settings,dict):settings={}
    manager=settings.get('manager','auto')
    return manager if manager in MANAGERS else 'auto',str(settings.get('command',''))

def configure_module(module,manager,custom,root):
    if manager not in MANAGERS:raise ValueError(tr('无效的更新程序'))
    if manager=='custom' and not custom.strip():raise ValueError(tr('请输入自定义更新命令'))
    result=dict(module)
    result['adws-update']={'manager':manager,'command':custom.strip()}
    result['on-click']=shlex.join([sys.executable,str(root/'tools/adws_topbar_update.py'),'--manager',manager,*(['--command',custom.strip()] if manager=='custom' else [])])
    result['on-click-right']=shlex.join(['bash',str(root/'adws'),'config','--tab','waybar'])
    result.setdefault('format','')
    result['tooltip-format']=tr('系统更新 · 右键配置')
    return result

def main():
    parser=argparse.ArgumentParser(description=tr('在默认终端中执行系统更新'))
    parser.add_argument('--manager',choices=MANAGERS,default='auto');parser.add_argument('--command',default='')
    args=parser.parse_args()
    try:
        command=resolve_command(args.manager,args.command)
        subprocess.Popen(terminal_command(command),cwd=Path.home(),start_new_session=True)
    except (ValueError,RuntimeError,OSError) as error:
        print(str(error),file=sys.stderr)
        if shutil.which('notify-send'):subprocess.run(['notify-send','ADWS',str(error)],check=False,timeout=5)
        return 1
    return 0
if __name__=='__main__':sys.exit(main())
