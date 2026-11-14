"""Reviewed, persistent installer plans. Planning never changes the desktop."""
from __future__ import annotations
import argparse
import configparser
import datetime
import contextlib
import fcntl
import hashlib
import json
import os
import platform
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile

from adws_install_ui import choose, interactive, prompt, select_targets, text_entry

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 1
DEFAULT_PACKAGES = {'terminal':'foot','browser':'firefox','file_manager':'thunar','text_editor':'mousepad'}
APP_ROLES = {'terminal': ('TerminalEmulator', ()), 'browser': ('WebBrowser', ('x-scheme-handler/http','x-scheme-handler/https','text/html')),
             'file_manager': ('FileManager', ('inode/directory',)), 'text_editor': ('TextEditor', ('text/plain',))}


def state_root():
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'adws/installer'


def write_json(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.adws-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out, ensure_ascii=False, indent=2); out.write('\n'); out.flush(); os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def fingerprint(root):
    digest = hashlib.sha256()
    files = [root/'install.sh', root/'adws', root/'build-info.json',root/'prebuilt/manifest.json']
    from adws_prebuilt import NAMES
    files.extend(root/'prebuilt'/name for name in NAMES)
    for folder in ('tools','scripts','config','src','vendor'):
        files.extend(p for p in (root/folder).rglob('*') if p.is_file() and not set(p.relative_to(root).parts).intersection({'target','__pycache__','.git','state'}) and p.suffix not in ('.so','.o','.pyc'))
    # The source build and the archive may share a version label but differ.
    for p in sorted(set(files)):
        if p.exists(): digest.update(str(p.relative_to(root)).encode()); digest.update(p.read_bytes())
    return digest.hexdigest()


def executable_argv(argv):
    """Validate desktop Exec wrappers without running user-provided commands."""
    if not argv or not shutil.which(argv[0]): return False
    if Path(argv[0]).name != 'env': return True
    # env itself being installed is not proof that its target application exists.
    remaining = list(argv[1:]);search_path=None
    while remaining:
        value = remaining.pop(0)
        if value == '--': break
        if value in ('-i','--ignore-environment'): continue
        if value in ('-u','--unset'):
            if not remaining: return False
            remaining.pop(0); continue
        if value.startswith('--unset='): continue
        if value.startswith('-'): return False
        if '=' in value and value.partition('=')[0].isidentifier():
            if value.startswith('PATH='):search_path=value.partition('=')[2]
            continue
        remaining.insert(0,value); break
    return bool(remaining) and bool(shutil.which(remaining[0],path=search_path))


def desktop_background_entry(argv):
    """Recognize explicit service launch modes without executing the entry.

    Foot's server entry is visible and has TerminalEmulator as its category,
    so NoDisplay alone cannot distinguish it from a window launcher. Inspect
    executable arguments (including env wrappers), not translated app names or
    desktop IDs. Unknown launchers remain eligible; this is not a promise about
    arbitrary third-party programs' runtime behaviour.
    """
    target = list(argv)
    while target and Path(target[0]).name == 'env':
        target.pop(0)
        while target:
            value = target.pop(0)
            if value == '--': break
            if value in ('-i', '--ignore-environment'): continue
            if value in ('-u', '--unset'):
                if not target: return True
                target.pop(0); continue
            if value.startswith('--unset='): continue
            if '=' in value and value.partition('=')[0].isidentifier(): continue
            if value.startswith('-'): return True
            target.insert(0, value); break
    if not target: return True
    program = Path(target[0]).name
    if program.endswith(('-server', '-daemon')): return True
    background = {'--server', '--daemon', '--daemonize', '--headless',
                  '--no-window', '--no-startup-window', '--background-mode'}
    # Options after -e/-- belong to the program launched inside a terminal, not
    # to the terminal itself. A title/name containing "server" is harmless.
    values = {'--title', '--class', '--app-id', '--config', '--font', '--term',
              '--working-directory', '--socket', '--listen-on'}
    arguments = iter(target[1:])
    for arg in arguments:
        if arg in ('--', '-e', '--execute', '--command'): break
        if arg in values:
            next(arguments, None); continue
        if arg.partition('=')[0] in background: return True
        if program == 'foot' and arg.startswith('-s') and not arg.startswith('--'): return True
    return False


def desktop_inventory():
    """Inventory all installed desktop apps, including non-default MIME handlers."""
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')
    folders = [data, *map(Path, (os.environ.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share').split(':'))]
    result=[]; seen=set()
    for folder in folders:
        appdir=folder/'applications'
        for path in sorted(appdir.rglob('*.desktop')):
            desktop_id=str(path.relative_to(appdir)).replace('/','-')
            if desktop_id in seen: continue
            seen.add(desktop_id)
            try:
                ini=configparser.ConfigParser(interpolation=None,strict=False); ini.read(path)
                row=ini['Desktop Entry']
                if row.get('Type')!='Application' or row.getboolean('Hidden',False): continue
                argv=shlex.split(row.get('Exec',''))
                argv=[a for a in argv if a not in ('%f','%F','%u','%U','%i','%c','%k')]
                if not argv or any('%' in a for a in argv) or not executable_argv(argv): continue
                if row.get('TryExec') and not shutil.which(row['TryExec']): continue
                result.append({'desktop_id':desktop_id,'name':row.get('Name',path.stem),'argv':argv,
                               'categories':row.get('Categories','').split(';'),'terminal':row.getboolean('Terminal',False),
                               # Hidden MIME handlers remain in the migration
                               # inventory, but must not become normal defaults.
                               'no_display':row.getboolean('NoDisplay',False),
                               'background_only':desktop_background_entry(argv)})
            except (OSError,ValueError,KeyError,configparser.Error): continue
    return result


def installed_apps():
    result={role:[] for role in APP_ROLES}
    for app in desktop_inventory():
        if app.get('no_display') or app.get('background_only'): continue
        for role,(category,_) in APP_ROLES.items():
            if category in app['categories'] and not app['terminal']:
                result[role].append({key:app[key] for key in ('desktop_id','name','argv')})
    return result


def fresh_file_manager(mode):
    if mode != 'fresh':
        return False
    state = Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')
    for name in ('adws', 'mnws'):
        try:
            inventory = json.loads((state / name / 'install-record.json').read_text())
        except FileNotFoundError:
            continue
        except (ValueError, OSError):
            return False  # Unknown installation state: keep the user's association.
        # ADWS's record supersedes the legacy MNWS inventory after migration.
        return isinstance(inventory, dict) and inventory.get('uninstalled') is True
    return True


def thunar_entry(app):
    # The distribution supplies thunar.desktop; other releases can use a
    # reverse-DNS desktop ID for the same graphical launcher.
    return (app['desktop_id'] in ('thunar.desktop', 'org.xfce.Thunar.desktop')
            or Path(app['argv'][0]).name.lower() == 'thunar' and len(app['argv']) == 1)


def choose_applications(mode, choices):
    """Collect choices before computing the reviewed package list."""
    for role, apps in installed_apps().items():
        if choices.get(role) or not apps:
            continue
        if interactive():
            labels = [a['name'] for a in apps]
            if role == 'file_manager':
                labels.insert(0, '使用 Thunar' if fresh_file_manager(mode) else '保留系统默认文件管理器')
            role_name = {'terminal': '终端', 'browser': '浏览器', 'file_manager': '文件管理器', 'text_editor': '文本编辑器'}[role]
            index = choose('选择默认' + role_name, labels)
            if role == 'file_manager' and index == 0:
                continue
            choices[role] = apps[index - int(role == 'file_manager')]['desktop_id']
            continue
        print(role+': '+', '.join(f'{i+1} {a["name"]}' for i,a in enumerate(apps)))
        if role == 'file_manager':
            default = 'Thunar' if fresh_file_manager(mode) else '保留系统默认文件管理器'
            value = input(f'选择已安装应用 [回车：{default}] ').strip()
            if not value:
                continue
        else:
            value = input('选择已安装应用 [1] ').strip() or '1'
        if not value.isdigit() or not 1 <= int(value) <= len(apps):
            raise ValueError('无效应用选择')
        choices[role] = apps[int(value)-1]['desktop_id']


def prebuilt_status(root):
    from adws_prebuilt import verify_artifacts, PrebuiltIntegrityError
    try:
        data=verify_artifacts(root)
        if data is None:return {'status':'missing','action':'source-build-required'}
        if platform.freedesktop_os_release().get('ID')!='arch' or platform.machine()!='x86_64':
            return {'status':'incompatible','action':'source-build-required','sha256':data['sha256']}
        return {'status':'verified','action':'install-prebuilt','sha256':data['sha256'],
                'compatibility':'运行依赖安装后核对动态库及 ABI；不匹配只按已批准的源码回退处理。'}
    except (OSError,ValueError,TypeError,AttributeError,PrebuiltIntegrityError) as exc:return {'status':'integrity-error','detail':str(exc)}


def selected_plan(mode, root=ROOT, choices=None, features=None, migration_source=None):
    from adws_install_features import feature_plan, provider_hints, MANAGERS, THUNAR_PACKAGES
    from adws_setup import PACKAGES, cargo_source_configuration
    from adws_windows import config_path
    manager = next((p for p in MANAGERS if shutil.which(p)), None)
    if not manager: raise ValueError('未找到受支持的包管理器；不能生成可执行安装计划。')
    config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')
    hints = provider_hints(config, niri_path=config_path(), environ=os.environ)
    available = installed_apps(); choices = choices or {}
    fresh_manager = fresh_file_manager(mode)
    applications = {}
    for role in APP_ROLES:
        wanted = choices.get(role)
        if role == 'file_manager' and not wanted:
            if not fresh_manager:
                applications[role] = {'policy':'preserve','desktop_id':None,
                                      'name':'保留系统默认文件管理器','argv':['xdg-open', str(Path.home())]}
                continue
            selected = next((a for a in available[role] if thunar_entry(a)), None)
            applications[role] = selected or {'desktop_id':None,'name':'Thunar',
                                               'argv':['thunar'],'install_package':THUNAR_PACKAGES[manager][0]}
            continue
        selected = next((a for a in available[role] if a['desktop_id']==wanted),None) if wanted else next(iter(available[role]),None)
        if wanted and not selected: raise ValueError(f'{role}: 所选应用未安装或不可运行：{wanted}')
        applications[role] = selected or {'desktop_id':None,'name':DEFAULT_PACKAGES[role], 'argv':[DEFAULT_PACKAGES[role]],'install_package':DEFAULT_PACKAGES[role]}
    include_file_manager = fresh_manager and (not choices.get('file_manager') or thunar_entry(applications['file_manager']))
    dependency = feature_plan(mode, manager, selected=features, provider_hints=hints, include_file_manager=include_file_manager)
    plan = {'schema_version':SCHEMA,'mode':mode,'source_root':str(root.resolve()),'source_fingerprint':fingerprint(root),
            'home':str(Path.home()),'data_home':str(Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')),'config_home':str(config),'niri_config':os.environ.get('NIRI_CONFIG',''),'niri_config_path':str(config_path()),'features':dependency,'applications':applications,
            'autostart':False,'topbar_autostart':False,'build_fallback':False,'niri_method':'repository',
            'mirror':'existing' if cargo_source_configuration(dict(os.environ),root) else 'official',
            'migration_source':str(Path(migration_source).expanduser().resolve()) if migration_source else None,
            'migration_categories':[], 'login_theme':'preserve','boot_theme':'preserve',
            'package_candidates':list(dict.fromkeys(dependency['packages']+PACKAGES[manager]['python']+['xdg-utils','fontconfig'])),
            'provider_plan':hints, 'blocking':[],
            'prebuilt':prebuilt_status(root),'acceptance':'必须在 Niri 图形会话完成，依赖就绪不等于功能通过'}
    if dependency.get('conflicts'):
        plan['blocking'].append('输入法、通知或壁纸的现有归属需要审核：'+json.dumps(dependency['conflicts'],ensure_ascii=False))
    if mode=='migrate' and not migration_source: plan['blocking'].append('迁移模式需要 --from-home 指定只读来源目录')
    plan['package_candidates'].extend(a['install_package'] for a in applications.values() if 'install_package' in a)
    return plan


WAYBAR_DEFAULTS = ('config-bottom.jsonc', 'style-bottom.css', 'modules.jsonc', 'colors.css')


def config_state(path):
    if path.is_symlink():
        return {'link': os.readlink(path)}
    if path.is_file():
        return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return None


def replace_reviewed_defaults(plan):
    folder = Path(plan['config_home']) / 'waybar'
    targets = plan.get('replace_waybar_defaults', {})
    for name, expected in targets.items():
        if name not in WAYBAR_DEFAULTS or expected is None or config_state(folder / name) != expected:
            raise ValueError('待覆盖配置已变化，请重新审核：' + name)
    # The enclosing transaction has backed up each target. Deployment installs
    # missing templates and records ownership using the usual installation path.
    for name in targets:
        (folder / name).unlink()


def approved_plan():
    path = os.environ.get('ADWS_INSTALL_PLAN')
    if not path: return None
    plan = json.loads(Path(path).read_text())
    if plan.get('schema_version') != SCHEMA or plan.get('approved') is not True:
        raise ValueError('无效或未确认的安装计划')
    return plan


def configure_defaults(plan):
    # Revalidate: a removed program must never become the system default.
    now = installed_apps()
    writable = {role:app for role, app in plan['applications'].items()
                if not (role == 'file_manager' and app and app.get('policy') == 'preserve')}
    for role, selected in writable.items():
        if not selected or selected not in now[role]: raise ValueError('默认应用已变化，请重新生成计划：'+role)
    config = Path(plan['config_home'])
    write_json(config/'adws/default-terminal.json', {'desktop_id':plan['applications']['terminal']['desktop_id']})
    for role, app in writable.items():
        for mime in APP_ROLES[role][1]:
            subprocess.run(['xdg-mime','default',app['desktop_id'],mime],check=True,timeout=20)
            actual = subprocess.check_output(['xdg-mime','query','default',mime],text=True,timeout=20).strip()
            if actual != app['desktop_id']: raise RuntimeError('默认应用关联未生效：'+mime)


def niri_rule_include(plan):
    """The generated rule include can live outside XDG_CONFIG_HOME/niri."""
    rules=Path(plan['source_root'])/'config/adws-windows.kdl'
    if not rules.is_file():return None
    digest=hashlib.sha256(rules.read_bytes()).hexdigest()[:20]
    return Path(plan['niri_config_path']).parent/('.adws-install-'+digest+'.kdl')


def deployment_receipt(plan):
    paths=[Path(plan['niri_config_path']),Path(plan['config_home'])/'adws/default-terminal.json',Path(plan['config_home'])/'mimeapps.list']
    paths += [Path(p) for p in plan.get('command_plan',{}).get('profiles',{})]
    paths += list((Path(plan['home'])/'.local/lib/waybar').glob('lib*.so'))
    paths += [Path(plan['source_root'])/'libexec'/name for name in ('adws-start-menu','adws-plugin-runner')]
    for name in ('env_file',):
        if plan.get('session_plan',{}).get(name):paths.append(Path(plan['session_plan'][name]))
    paths += [Path(row['path']) for row in plan.get('session_plan',{}).get('profile_writes',[])]
    paths += [Path(row['path']) for row in plan.get('palette_plan',{}).get('files',[])]
    paths += [Path(p) for p in plan.get('package_owner_plan',{}).get('snapshot_targets',[])]
    for key in ('niri_relocation', 'startup_plan', 'topbar_migration', 'bottom_library_migration'):
        paths += [Path(p) for p in plan.get(key,{}).get('snapshot_targets',[])]
    if rule_include:=niri_rule_include(plan):paths.append(rule_include)
    if plan.get('palette_plan'):
        paths.append(Path(plan['config_home'])/'adws/palette-sync.json')
    from adws_install_migration import destination_path
    paths += [destination_path(plan['migration_plan'],e) for e in plan.get('migration_plan',{}).get('entries',[])]
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


def verify_receipt(receipt):
    changed=[]
    for name,digest in receipt.items():
        try:matches=hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest
        except OSError:matches=False
        if not matches:changed.append(name)
    if changed:raise ValueError('安装后文件发生变化；保留这些修改，请重新预览安装计划：'+', '.join(changed))


def verify_provider_sources(plan):
    """Stop before touching configuration if reviewed provider ownership changed."""
    hints=plan.get('provider_plan',{})
    changed=[]
    for name,digest in hints.get('source_hashes',{}).items():
        try:matches=hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest
        except OSError:matches=False
        if not matches:changed.append(name)
    for rows in hints.get('evidence',{}).values():
        for row in rows:
            if row.get('origin')=='process-environment' and os.environ.get(row['key'])!=row['value']:
                changed.append(row['key'])
    if changed:raise ValueError('已审核的服务归属或输入法环境发生变化；保留现状，请重新生成计划：'+', '.join(dict.fromkeys(changed)))


def refreshed_niri_relocation(plan):
    """Rebase only the session fragment that this reviewed transaction wrote.

    The original include graph was checked before packages and before writes.
    A reviewed session update can legitimately change its environment fragment;
    every other input and every proposed command replacement must stay intact.
    """
    previous=plan.get('niri_relocation')
    if not previous:return None
    session=plan.get('session_plan',{})
    allowed={}
    if session.get('env_file'):
        allowed[str(Path(session['env_file']).resolve())]=hashlib.sha256(session['env_kdl'].encode()).hexdigest()
    from adws_install_niri import relocation_plan
    current=relocation_plan(plan['niri_config_path'],plan.get('source_migration'))
    if current['conflicts']:raise ValueError('安装路径迁移出现新的配置冲突，请重新审核。')
    old_graph=previous.get('audit',{});new_graph=current.get('audit',{})
    if (current.get('resolved_config_path')!=previous.get('resolved_config_path')
            or old_graph.get('niri_includes',[])!=new_graph.get('niri_includes',[])
            or [name for name in old_graph.get('niri_files',[]) if name not in allowed]
               !=[name for name in new_graph.get('niri_files',[]) if name not in allowed]):
        raise ValueError('Niri 配置包含关系发生变化，请重新审核安装路径迁移。')
    before=previous.get('source_hashes',{});after=current.get('source_hashes',{})
    for name in before.keys() | after.keys():
        if before.get(name)==after.get(name):continue
        if name not in allowed or after.get(name)!=allowed[name]:
            raise ValueError('安装路径迁移的配置来源发生变化：'+name)
    signature=lambda proposal:[(row['path'],row['before'],row['after']) for row in proposal.get('replacements',[])]
    if (current['files']!=previous['files'] or current['originals']!=previous['originals']
            or signature(current)!=signature(previous)
            or current['snapshot_targets']!=previous['snapshot_targets']):
        raise ValueError('安装路径迁移范围发生变化，请重新审核。')
    return current


def write_result(plan, progress, directory, acceptance=None, error=None):
    """One durable result record for success, pending activation and failure."""
    steps=progress.get('steps',{})
    report={'schema_version':1,'status':progress.get('status','failed'),'mode':plan['mode'],
            'completed':[k for k,v in steps.items() if v.get('status')=='passed'],
            'failed':[k for k,v in steps.items() if v.get('status') in ('failed','recovery-incomplete')],
            'rolled_back':[k for k,v in steps.items() if v.get('status')=='rolled-back'],
            'pending':(acceptance or {}).get('pending',['session-acceptance'] if progress.get('deployment_receipt') and progress.get('status')!='complete' else []),
            'skipped':([] if plan.get('autostart') or steps.get('autostart',{}).get('status')=='passed' else ['autostart']) + ([] if plan.get('palette_plan') else ['palette-registration']),
            'backups':progress.get('backups',[]),'log':str(Path(directory)/'install.log'),
            'activation':plan.get('session_plan',{}).get('activation','manual-start'),
            'packages':'已安装系统包保留，不随配置回滚卸载。',
            'system_upgrade':bool(plan.get('system_upgrade')),
            'package_review':plan.get('package_review'),
            'source_migration':plan.get('source_migration'),
            'topbar_migration':plan.get('topbar_migration'),
            'bottom_library_migration':plan.get('bottom_library_migration'),
            'limitations':plan.get('session_plan',{}).get('limitations',[])+plan.get('palette_plan',{}).get('limitations',[])+plan.get('topbar_migration',{}).get('limitations',[]),
            'error':error}
    themes=Path(directory)/'system-theme-result.json'
    if themes.is_file():
        theme_result=json.loads(themes.read_text())
        report['system_themes']=theme_result
        if theme_result.get('backup'):report['backups']=[*report['backups'],theme_result['backup']]
    niri_report=Path(directory)/'niri-configuration-plan.json'
    if niri_report.is_file():report['niri_skipped']=json.loads(niri_report.read_text()).get('skipped',[])
    report['recovery_errors']=progress.get('recovery_errors',[])
    report['configuration_restored']=progress.get('configuration_restored')
    write_json(Path(directory)/'result.json',report)
    lines=['# ADWS 安装结果','', '状态：'+report['status'], '模式：'+plan['mode'],'']
    for key,title in [('completed','已完成'),('failed','失败'),('rolled_back','已回滚'),('skipped','跳过'),('pending','待验收'),('backups','备份')]:
        lines += [title+'：'+('、'.join(map(str,report[key])) or '无'),'']
    lines += ['启用：'+('会话环境和服务在下次登录生效；无需仅为安装重新启动整台电脑。' if report['activation']=='next_login' else '按所选启动方式启用组件。'),'',report['packages'],'','日志：'+report['log']]
    if report['system_upgrade']:
        lines += ['','本次包含已选择的系统完整升级；内核与系统组件的重新启动要求以包管理器输出为准。']
    if error:lines += ['','原因：'+str(error)]
    (Path(directory)/'result.md').write_text('\n'.join(lines)+'\n')
    return report


def record_acceptance(journal, directory):
    from adws_install_acceptance import evaluate
    report=evaluate()
    write_json(Path(directory)/'acceptance.json',report)
    journal.data['status']='complete' if report['complete'] else 'acceptance-failed' if report['failed'] else 'pending-acceptance'
    journal.save()
    write_result(journal.plan,journal.data,directory,report)
    print('配置部署已完成；功能验收状态：'+journal.data['status'])
    print('日志、进度与备份索引：'+str(directory))
    return 0 if report['complete'] else 1 if report['failed'] else 2


class Journal:
    def __init__(self, directory, plan):
        self.directory=Path(directory); self.path=self.directory/'progress.json'; self.plan=plan
        if self.path.exists():
            self.data=json.loads(self.path.read_text())
            if self.data['plan_digest'] != self.digest(plan): raise ValueError('计划或源文件已改变，请重新预览，不能复用旧步骤。')
        else: self.data={'schema_version':SCHEMA,'plan_digest':self.digest(plan),'steps':{},'status':'planned','backups':[]}
    @staticmethod
    def digest(plan): return hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
    def save(self): write_json(self.path,self.data)
    def step(self, name, operation, verify=None):
        row=self.data['steps'].get(name,{})
        if row.get('status')=='passed' and verify is not None and verify():
            row['revalidated']=True;self.save();return
        self.data['steps'][name]={'status':'running'};self.save()
        print('正在执行 · ' + name, flush=True)
        try:
            operation()
            if verify is not None and not verify(): raise RuntimeError('步骤复查失败：'+name)
        except BaseException as exc:
            self.data['steps'][name]={'status':'failed','error':str(exc)};self.data['status']='failed';self.save();raise
        self.data['steps'][name]={'status':'passed'};self.save()


def validate_execution(plan):
    if plan.get('approved') is not True or plan.get('schema_version') != SCHEMA: raise ValueError('安装计划未确认或版本无效。')
    if plan.get('data_home',str(Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share'))) != str(Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')): raise ValueError('目标数据目录已改变，需重新生成计划。')
    if plan.get('niri_config','') != os.environ.get('NIRI_CONFIG',''): raise ValueError('Niri 配置目标已改变，需重新生成计划。')
    if plan['config_home'] != str(Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')): raise ValueError('目标配置目录已改变，需重新生成计划。')
    if plan['source_fingerprint'] != fingerprint(Path(plan['source_root'])): raise ValueError('源码已改变，请重新生成计划。')
    if plan['home'] != str(Path.home()): raise ValueError('不能在另一个用户下执行此安装计划。')
    if plan['blocking']: raise ValueError('\n'.join(plan['blocking']))


def system_theme_action(plan, directory, *, rollback=None):
    from adws_install_boot_themes import invoke
    return invoke(plan,directory,rollback=rollback)


class InterpreterRestart(BaseException):
    """Leave every installer context before replacing the running interpreter."""
    def __init__(self, executable, directory, token, root):
        self.executable=executable
        self.argv=[executable,str(Path(root)/'tools/adws_install_workflow.py'),
                   '--continue-after-upgrade',str(directory),'--continuation-token',token]


def python_identity():
    # /proc keeps identifying the running inode even after pacman replaces it.
    info=os.stat('/proc/self/exe')
    return {'device':info.st_dev,'inode':info.st_ino,'version':list(sys.version_info[:3])}


def replacement_python():
    running=python_identity()
    candidate=Path(sys.executable)
    if not candidate.is_file():candidate=Path('/usr/bin/python3')
    try:disk=candidate.stat()
    except OSError as error:raise RuntimeError('系统升级后 Python 入口不可用；请修复 Python 后续装。') from error
    if (disk.st_dev,disk.st_ino)==(running['device'],running['inode']):return None
    code=('import json,os,sys; s=os.stat("/proc/self/exe"); '
          'print(json.dumps({"device":s.st_dev,"inode":s.st_ino,"version":list(sys.version_info[:3])}))')
    probe=subprocess.run([str(candidate),'-c',code],capture_output=True,text=True,timeout=15)
    try:target=json.loads(probe.stdout)
    except (ValueError,TypeError) as error:raise RuntimeError('升级后的 Python 无法启动；请修复后续装。') from error
    if probe.returncode or tuple(target.get('version',()))<(3,11) or (target.get('device'),target.get('inode'))!=(disk.st_dev,disk.st_ino):
        raise RuntimeError('升级后的 Python 身份或版本校验失败；请重新运行安装入口。')
    return str(candidate),target


def restart_after_python_upgrade(plan, journal):
    if not (plan.get('system_upgrade') and plan['features']['manager']=='pacman'):return
    replacement=replacement_python()
    if replacement is None:return
    if journal.data.get('interpreter_handoff'):
        raise RuntimeError('续装期间 Python 再次改变；为避免重复重启，请重新审核安装计划。')
    directory=journal.directory
    if directory.is_symlink() or directory.resolve().parent!=state_root().resolve() or directory.stat().st_uid!=os.getuid():
        raise ValueError('解释器续装必须使用当前用户的安装进度目录。')
    # The installer created this journal; a cooperative umask (0002) must not
    # make the private handoff fail its own directory permission check.
    directory.chmod(0o700)
    executable,target=replacement;token=os.urandom(32).hex()
    journal.data['interpreter_handoff']={'status':'pending','token_sha256':hashlib.sha256(token.encode()).hexdigest(),
        'target':target,'previous':python_identity(),'plan_digest':Journal.digest(plan),'executable':executable}
    journal.data['status']='interpreter-restart-pending';journal.save()
    print('系统升级已更换 Python；保存软件包进度，使用新解释器继续安装。')
    raise InterpreterRestart(executable,journal.directory,token,plan['source_root'])


def continuation_directory(directory):
    path=Path(directory)
    if not path.is_absolute() or path.is_symlink() or path.resolve().parent!=state_root().resolve():
        raise ValueError('无效的解释器续装目录。')
    for item in (path,path/'plan.json',path/'progress.json'):
        if item.is_symlink() or item.stat().st_uid!=os.getuid() or item.stat().st_mode&0o022:
            raise ValueError('解释器续装记录的所有者或权限无效。')
    return path


def consume_interpreter_handoff(plan, directory, token):
    continuation_directory(directory)
    journal=Journal(directory,plan);handoff=journal.data.get('interpreter_handoff',{})
    if (not plan.get('system_upgrade') or plan['features']['manager']!='pacman'
            or handoff.get('status')!='pending' or handoff.get('plan_digest')!=Journal.digest(plan)
            or handoff.get('token_sha256')!=hashlib.sha256(token.encode()).hexdigest()
            or journal.data.get('steps',{}).get('packages',{}).get('status')!='passed'
            or handoff.get('target')!=python_identity()):
        raise ValueError('解释器续装凭据已失效或与当前安装不符。')
    from adws_niri_install import installed_packages
    if not set(plan['package_candidates'])<=installed_packages('pacman',plan['package_candidates']):
        raise ValueError('升级后的依赖再次缺失；请重新审核计划，不自动重复完整升级。')
    handoff['status']='resumed';handoff.pop('token_sha256',None)
    journal.data['status']='packages-ready';journal.save()


def _execute(plan, directory):
    from adws_install_transaction import install, RecoveryError
    from adws_setup import prepare, install_packages
    from adws_niri_install import package_candidates, installed_packages
    from adws_install_niri import plan as niri_plan, apply as niri_apply
    validate_execution(plan)
    journal=Journal(directory,plan); journal.save()
    if journal.data.get('configuration_restored') is False:
        raise ValueError('上次安装的自动恢复未完成。请先根据备份恢复，或重新审核安装计划；不会重放旧计划覆盖现场。')
    if not journal.data.get('deployment_receipt') and plan.get('source_migration'):
        from adws_install_source_migration import verify_before
        verify_before(plan['source_migration'])
    if not journal.data.get('deployment_receipt') and plan.get('niri_relocation'):
        from adws_install_niri import verify_relocation
        verify_relocation(plan['niri_relocation'])
    if not journal.data.get('deployment_receipt') and plan.get('topbar_migration'):
        from adws_install_topbar_migration import verify_before
        verify_before(plan['topbar_migration'])
    if not journal.data.get('deployment_receipt') and plan.get('bottom_library_migration'):
        from adws_install_topbar_migration import verify_before
        verify_before(plan['bottom_library_migration'])
    plan_path=Path(directory)/'plan.json';write_json(plan_path,plan)
    oldenv=dict(os.environ)
    os.environ.update(ADWS_INSTALL_PLAN=str(plan_path),ADWS_INSTALL_MANAGED='1',ADWS_NIRI_METHOD=plan['niri_method'],
                      ADWS_BUILD_MIRROR='1' if plan['mirror']=='rsproxy' else '0')
    manager=plan['features']['manager']
    try:
        def packages():
            if manager=='pacman' and plan.get('system_upgrade'):
                from adws_install_arch_packages import verify_sources
                verify_sources(plan['package_review'])
                install_packages(programs=plan['package_candidates'], system_upgrade=True)
                return
            wanted=plan['package_candidates'];missing=set(wanted)-installed_packages(manager,wanted)
            candidates=package_candidates(manager,sorted(missing))
            absent=missing-set(candidates)
            if absent: raise RuntimeError('当前软件源缺少以下包，尚未更改配置：'+', '.join(sorted(absent)))
            if missing: install_packages(programs=sorted(missing))
        # This step survives rollback, but is checked against the package database on resume.
        journal.step('packages',packages,lambda:set(plan['package_candidates']) <= installed_packages(manager,plan['package_candidates']))
        restart_after_python_upgrade(plan,journal)
        if journal.data.get('deployment_receipt'):
            verify_receipt(journal.data['deployment_receipt'])
            return record_acceptance(journal,directory)
        verify_provider_sources(plan)
        package_owners=None
        if plan.get('package_owner_plan'):
            from adws_install_package_owners import reconcile_package_owners
            package_owners=reconcile_package_owners(plan['package_owner_plan'])
            write_json(Path(directory)/'package-owner-proposal.json',package_owners)
        resolved=json.loads(json.dumps(plan))
        available=installed_apps()
        for role, app in resolved['applications'].items():
            if 'install_package' in app:
                match=next((a for a in available[role] if (thunar_entry(a) if role == 'file_manager' else Path(a['argv'][0]).name == app['argv'][0])),None)
                if match is None: raise RuntimeError('应用安装后没有有效桌面入口：'+app['name'])
                resolved['applications'][role]=match
        runtime_plan=Path(directory)/'resolved-plan.json';write_json(runtime_plan,resolved)
        os.environ['ADWS_INSTALL_PLAN']=str(runtime_plan)
        nickname_change=None;theme_change=None;theme_started=False
        def operation(backup):
            nonlocal nickname_change,theme_change
            journal.data['backups'].append(str(backup));journal.save()
            replace_reviewed_defaults(plan)
            from adws_commands import ENTRIES
            for name, expected in plan.get('replace_commands', {}).items():
                path = Path(name)
                if (path.parent != Path.home() / '.local/bin' or path.name not in ENTRIES
                        or config_state(path) != expected or expected is None):
                    raise ValueError('待覆盖命令已变化，请重新审核：' + name)
            for name in plan.get('replace_commands', {}):
                Path(name).unlink()
            if package_owners:
                from adws_install_package_owners import apply_reviewed_package_owners
                journal.step('package-startup-ownership',lambda:write_json(Path(directory)/'package-owner-result.json',apply_reviewed_package_owners(package_owners,Path(backup)/'package-startup')))
            if plan.get('source_migration'):
                from adws_install_source_migration import apply as source_migrate
                journal.step('installation-source-migration',lambda:write_json(Path(directory)/'source-migration-result.json',source_migrate(plan['source_migration'],Path(backup)/'installation-source')))
            if plan.get('legacy_plan'):
                from adws_install_legacy import apply as legacy_apply
                journal.step('legacy-configuration',lambda:write_json(Path(directory)/'legacy-result.json',legacy_apply(plan['legacy_plan'],Path(backup)/'legacy')))
            if plan.get('topbar_migration'):
                from adws_install_topbar_migration import apply as topbar_migrate
                journal.step('topbar-source-migration',lambda:write_json(Path(directory)/'topbar-migration-result.json',topbar_migrate(plan['topbar_migration'],Path(backup)/'topbar-source')))
            journal.step('native-components',prepare)
            if plan.get('bottom_library_migration'):
                from adws_install_topbar_migration import apply as migrate_bottom_library
                journal.step('bottom-library-migration',lambda:write_json(Path(directory)/'bottom-library-migration-result.json',migrate_bottom_library(plan['bottom_library_migration'],Path(backup)/'bottom-library')))
            if plan['migration_source']:
                from adws_install_migration import plan_migration, apply_migration
                migration=plan['migration_plan']
                if migration.get('conflicts'): raise RuntimeError('迁移存在冲突，请先预览并解决：'+json.dumps(migration['conflicts'],ensure_ascii=False))
                def migrate():
                    result=apply_migration(migration,Path(backup)/'personal-migration')
                    write_json(Path(directory)/'migration-result.json',result)
                    if result['status']!='complete':raise RuntimeError('个人环境迁移仍有项目需要审核。')
                journal.step('migration',migrate)
            from adws_niri_install import validate
            from adws_niri_compat import niri_binary
            if plan.get('session_plan'):
                from adws_install_session_config import apply as session_apply
                journal.step('session-configuration',lambda:session_apply(plan['session_plan'],Path(backup)/'session',lambda p:validate(niri_binary(),p)))
            from adws_install_niri import action_commands
            actions=action_commands(Path(plan['source_root']),plan['features'],plan.get('session_plan',{}).get('lock_argv'))
            if actions['skipped']:raise RuntimeError('所选快捷键依赖未安装：'+json.dumps(actions['skipped'],ensure_ascii=False))
            relocation=refreshed_niri_relocation(plan)
            shortcuts = {r:a['argv'] for r,a in resolved['applications'].items()}
            shortcuts['file_manager'] = ['xdg-open', plan['home']]
            niri=niri_plan(plan['mode'], root=Path(plan['source_root']), config_path=plan['niri_config_path'], applications=shortcuts,startup=[],actions=actions['commands'],features=plan['features'],relocation=relocation)
            if niri['conflicts']: raise RuntimeError('Niri 配置冲突：'+json.dumps(niri['conflicts'],ensure_ascii=False))
            if plan.get('session_plan'):
                key=plan['niri_config_path'];line=plan['session_plan']['include_line']
                text=niri['files'].get(key,Path(key).read_text() if Path(key).exists() else '')
                if line not in text.splitlines():niri['files'][key]=text.rstrip()+'\n\n'+line+'\n'

            write_json(Path(directory)/'niri-configuration-plan.json',niri)
            journal.step('niri-configuration',lambda:niri_apply(niri,Path(backup)/'niri'))
            if plan.get('palette_plan'):
                from adws_palette_sync import register
                journal.step('palette-registration',lambda:write_json(Path(directory)/'palette-result.json',register(plan['palette_plan'],Path(backup)/'palette')))
            journal.step('default-applications',lambda:configure_defaults(resolved))
            from adws_niri_install import validate
            from adws_niri_compat import niri_binary
            if plan.get('startup_plan'):
                from adws_install_startup import plan as startup_plan, apply as startup_apply, owner_signature
                proposal=startup_plan(plan['config_home'],plan['startup_plan']['commands'],niri_path=plan['niri_config_path'],
                                      source_migration=plan.get('source_migration'),add_missing=plan['autostart'])
                # Config generation can alter hashes, but must not change existing ownership.
                if proposal['unknown'] or proposal['conflicts'] or owner_signature(proposal['owners'])!=owner_signature(plan['startup_plan']['owners']):
                    raise RuntimeError('自启动归属已变化，需要重新审核计划。')
                journal.step('autostart',lambda:startup_apply(proposal,Path(backup)/'startup',lambda p:validate(niri_binary(),p)))
            validate(niri_binary(),Path(plan['niri_config_path']))
            # Keep the old installation record until all reviewed path changes
            # are verified. Configuration deployment registers the new root.
            env=dict(os.environ,ADWS_INSTALL_TRANSACTION=plan['source_root'],ADWS_INSTALL_CONFIG_ONLY='1')
            from adws_install_transaction import checked_run
            journal.step('adws-configuration',lambda:checked_run(['bash',str(Path(plan['source_root'])/'scripts/adws-install.sh')],env=env,check=True))
            action=plan.get('migration_plan',{}).get('account_action',{})
            if action.get('policy')=='set':
                from adws_install_personal import apply_nickname
                def nickname():
                    nonlocal nickname_change
                    nickname_change=apply_nickname(action)
                    write_json(Path(directory)/'nickname-change.json',nickname_change)
                journal.step('account-nickname',nickname)
            if plan.get('theme_plan',{}).get('changes'):
                def themes():
                    nonlocal theme_change,theme_started
                    theme_started=True
                    theme_change=system_theme_action(plan,directory)
                    write_json(Path(directory)/'system-theme-result.json',theme_change)
                journal.step('system-themes',themes)
        extra=[Path(plan['config_home'])/'mimeapps.list',Path(plan['config_home'])/'niri',Path(plan['niri_config_path'])]
        if rule_include:=niri_rule_include(plan):extra.append(rule_include)
        from adws_install_migration import destination_path
        extra += [destination_path(plan['migration_plan'],e) for e in plan.get('migration_plan',{}).get('entries',[])]
        extra += [Path(p) for p in plan.get('session_plan',{}).get('snapshot_targets',[])]
        extra += [Path(p) for p in plan.get('command_plan',{}).get('profiles',{})]
        extra += [Path(row['path']) for row in plan.get('palette_plan',{}).get('files',[])]
        extra += [Path(p) for p in plan.get('package_owner_plan',{}).get('snapshot_targets',[])]
        extra += [Path(p) for p in plan.get('legacy_plan',{}).get('snapshot_targets',[])]
        extra += [Path(p) for p in plan.get('source_migration',{}).get('snapshot_targets',[])]
        for key in ('niri_relocation', 'startup_plan', 'topbar_migration', 'bottom_library_migration'):
            extra += [Path(p) for p in plan.get(key,{}).get('snapshot_targets',[])]
        if plan.get('palette_plan'):extra.append(Path(plan['config_home'])/'adws/palette-sync.json')
        try: install(Path(plan['source_root']),operation=operation,extra_paths=extra,
                     restart_profiles=plan.get('topbar_migration',{}).get('restart_profiles',[]))
        except BaseException as original:
            recovery_errors=[]
            configuration_restored=getattr(original,'configuration_restored',True)
            external_recovery_failed=set()
            if not configuration_restored:recovery_errors.append('配置快照未完整恢复：'+str(original))
            elif isinstance(original,RecoveryError):recovery_errors.append('组件未完整恢复：'+str(original))
            if theme_started:
                try:
                    from adws_install_boot_themes import operation_backup
                    backup=(theme_change or {}).get('backup') or operation_backup(directory)
                    if backup:
                        restored=system_theme_action(plan,directory,rollback=backup)
                        write_json(Path(directory)/'system-theme-rollback.json',restored)
                        if restored.get('conflicts'):
                            recovery_errors.append('系统主题：'+str(restored['conflicts']));external_recovery_failed.add('system-themes')
                except Exception as error:
                    recovery_errors.append('系统主题：'+str(error));external_recovery_failed.add('system-themes')
            if nickname_change is not None:
                try:
                    from adws_install_personal import rollback_nickname
                    restored=rollback_nickname(nickname_change)
                    write_json(Path(directory)/'nickname-rollback.json',restored)
                    if restored.get('status')=='conflict':
                        recovery_errors.append('显示昵称已在安装后修改，保留现值。');external_recovery_failed.add('account-nickname')
                except Exception as error:
                    recovery_errors.append('显示昵称：'+str(error));external_recovery_failed.add('account-nickname')
            # Mark only proven restoration. A bar that will not stop can
            # prevent snapshot restoration, leaving deployed files in place.
            for name,row in journal.data['steps'].items():
                if name=='packages' or row['status']!='passed':continue
                if name in external_recovery_failed:row['status']='recovery-incomplete'
                elif configuration_restored:row['status']='rolled-back'
            journal.data['configuration_restored']=configuration_restored
            journal.data['status']='failed' if configuration_restored else 'recovery-incomplete'
            journal.data['recovery_errors']=recovery_errors;journal.save()
            if recovery_errors:raise RuntimeError('安装失败；以下恢复仍需处理：'+'；'.join(recovery_errors)) from original
            raise
        journal.data.pop('configuration_restored',None)
        journal.data.pop('recovery_errors',None)
        journal.data['deployment_receipt']=deployment_receipt(plan)
        # Deployment is already committed. Persist that boundary before IPC or
        # user-session checks can be interrupted, so resume never replays it.
        journal.data['status']='pending-acceptance';journal.save()
        write_result(plan,journal.data,directory)
        return record_acceptance(journal,directory)
    finally:
        os.environ.clear();os.environ.update(oldenv)


@contextlib.contextmanager
def install_log(path):
    """Tee child output as well as Python output; never log environment/passwords."""
    sys.stdout.flush(); sys.stderr.flush()
    out, err = os.dup(1), os.dup(2)
    start = path.stat().st_size if path.exists() else 0
    package_error = None
    tee = subprocess.Popen(['tee','-a',str(path)], stdin=subprocess.PIPE, stdout=out, stderr=err)
    try:
        os.dup2(tee.stdin.fileno(),1); os.dup2(tee.stdin.fileno(),2)
        yield
    except subprocess.CalledProcessError as error:
        if isinstance(error.cmd, (list, tuple)) and 'pacman' in error.cmd[:2]:
            package_error = error
        else:
            raise
    finally:
        sys.stdout.flush(); sys.stderr.flush()
        os.dup2(out,1); os.dup2(err,2); os.close(out); os.close(err)
        tee.stdin.close(); tee.wait(timeout=10)
    if package_error is not None:
        from adws_install_arch_packages import transaction_issue
        with path.open('rb') as log:
            log.seek(max(start, path.stat().st_size - 32768))
            issue = transaction_issue(log.read().decode(errors='replace'))
        raise RuntimeError(issue['message'] + '\n完整日志：' + str(path)) from package_error


@contextlib.contextmanager
def cancellation_signals():
    """Give SIGTERM the same child cleanup and rollback path as Ctrl+C."""
    def cancel(_signum,_frame):
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        raise KeyboardInterrupt('安装被终止')
    previous=signal.signal(signal.SIGTERM,cancel)
    try:yield
    finally:signal.signal(signal.SIGTERM,previous)


def execute(plan, directory, *, continuation_token=None):
    validate_execution(plan)
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    state_root().mkdir(parents=True,exist_ok=True)
    with (state_root()/'execution.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if continuation_token is not None:consume_interpreter_handoff(plan,directory,continuation_token)
        with cancellation_signals(), install_log(directory/'install.log'):
            try:
                result=_execute(plan,directory)
                failed=directory/'failure.json'
                if failed.exists():failed.rename(directory/('previous-failure-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json'))
                return result
            except InterpreterRestart as pending:
                restart=pending
            except BaseException as error:
                progress=json.loads((directory/'progress.json').read_text()) if (directory/'progress.json').exists() else None
                committed=bool(progress and progress.get('deployment_receipt'))
                if committed:
                    progress['status']='pending-acceptance' if isinstance(error,KeyboardInterrupt) else 'review-required'
                    write_json(directory/'progress.json',progress)
                write_json(directory/'failure.json',{'status':'deployment-complete-verification-pending' if committed else 'failed','error':str(error),
                    'packages':'已安装的软件包不会因配置回滚而卸载',
                    'resume':('重新运行 install.sh --resume；核对部署收据后继续验收，不重写配置' if committed else
                              '自动恢复未完成；先根据备份恢复或重新审核计划，旧计划不能自动重放' if progress and progress.get('configuration_restored') is False else
                              '重新运行 install.sh --resume；配置步骤会复查并重新应用')})
                if progress:write_result(plan,progress,directory,error=str(error))
                print(('配置已部署；验收中断或需要审核：' if committed else '安装未完成：')+str(error),file=sys.stderr)
                raise
    # The old _execute restored its temporary environment; tee and both lock
    # scopes have ended. No stale interpreter may enter a config transaction.
    try:os.execve(restart.executable,restart.argv,dict(os.environ))
    except OSError as error:
        progress=json.loads((directory/'progress.json').read_text())
        progress['status']='failed';progress['interpreter_handoff']['status']='launch-failed'
        write_json(directory/'progress.json',progress)
        write_json(directory/'failure.json',{'status':'failed','error':str(error),
                   'resume':'Python 已升级；修复启动问题后重新运行 install.sh --resume，已成功的软件包不会重复安装。'})
        write_result(plan,progress,directory,error=str(error))
        raise


def review_plan(plan):
    from adws_install_features import FEATURE_MANIFEST
    skipped = [FEATURE_MANIFEST[name]['label'] for name in plan.get('skipped_features', [])]
    skipped.extend(plan.get('skipped_packages', []))
    resolution = plan.get('package_resolution')
    package_line = ('需补齐的软件包：' + (' '.join(resolution['missing']) or '无')
                    if resolution else '候选软件包：' + ' '.join(plan['package_candidates']))
    summary = '\n'.join([
        '方案：' + plan['mode'] + '    配置目录：' + plan['config_home'],
        '默认应用：' + '、'.join(app['name'] for app in plan['applications'].values()),
        '备份后覆盖：' + ('、'.join([*plan.get('replace_waybar_defaults', {}), *plan.get('replace_commands', {})]) or '无'),
        '跳过的可选项：' + ('、'.join(skipped) or '无'),
        package_line,
    ])
    if resolution:
        summary += '\n已满足依赖：' + str(len(resolution['satisfied'])) + ' 项'
        for requirement, provider in resolution['providers'].items():
            summary += f'\n  {requirement} ← {provider}'
    if plan['blocking']:
        summary = '待处理：' + str(len(plan['blocking'])) + ' 项，继续查看原因。\n' + summary
    if interactive():
        import pydoc
        while True:
            action = choose('审核安装计划', ['继续', '查看软件包明细', '查看完整计划'], detail=summary)
            if action == 0:
                break
            if action == 1:
                lines = [summary]
                for feature in plan['features']['features']:
                    lines.append(feature['label'] + '：' + (' '.join(feature['packages']) or '沿用已有实现'))
                if resolution:
                    lines.append('已满足：' + ' '.join(resolution['satisfied']))
                pydoc.pager('\n\n'.join(lines))
            else:
                pydoc.pager(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(summary)


def main(argv=None):
    parser=argparse.ArgumentParser(description='ADWS 统一安装：先预览，再执行；持久续装和独立验收。')
    parser.add_argument('--mode',choices=('fresh','integrate','migrate'))
    parser.add_argument('--plan',action='store_true',help='只显示计划，不修改任何配置')
    parser.add_argument('--resume',action='store_true');parser.add_argument('--verify',action='store_true')
    parser.add_argument('--continue-after-upgrade',help=argparse.SUPPRESS)
    parser.add_argument('--continuation-token',help=argparse.SUPPRESS)
    parser.add_argument('--exercise',action='append',choices=['screenshot'],default=[])
    parser.add_argument('--confirm',action='append',choices=['preview','clipboard','launch','screenshot'],default=[])
    parser.add_argument('--migration-categories',nargs='+',default=None)
    parser.add_argument('--migration-decisions',type=Path)
    parser.add_argument('--source-config-home');parser.add_argument('--source-data-home')
    parser.add_argument('--login-theme',default='preserve',help='选择已安装的 SDDM 主题；默认保留登录管理器及现状')
    parser.add_argument('--boot-theme',default='preserve',help='选择已安装的 Plymouth 主题；默认保留引导及启动图')
    parser.add_argument('--nickname',help='显式选择迁移后的显示昵称；不提供则保留')
    parser.add_argument('--autostart',action=argparse.BooleanOptionalAction,default=None)
    from adws_palette_sync import TARGETS
    parser.add_argument('--palette-targets',nargs='+',choices=TARGETS,help='明确选择随壁纸配色同步的终端、通知或默认图标')
    parser.add_argument('--palette-icon-base',help='图标配色继承的现有图标主题')
    parser.add_argument('--foot-shell',choices=('bash','zsh'),help='给所选 Shell 注册 Foot 终端内实时配色')
    parser.add_argument('--skip-feature', action='append', choices=('brightness','lock','palette'),
                        help='跳过可选功能及其专用依赖，可重复指定')
    parser.add_argument('--input-addons', choices=('auto','install','skip'), default='auto',
                        help='可选 Fcitx 拼音扩展；全新中文拼音配置需要此包')
    parser.add_argument('--from-home');parser.add_argument('--build-fallback',action='store_true')
    parser.add_argument('--system-upgrade',action=argparse.BooleanOptionalAction,default=None,
                        help='Arch：完整升级系统并补齐依赖；使用临时仓库预览，实际包事务需确认，不执行单独 -Sy')
    for role in APP_ROLES: parser.add_argument('--'+role.replace('_','-'))
    args=parser.parse_args(argv)
    if args.continue_after_upgrade is not None or args.continuation_token is not None:
        if not args.continue_after_upgrade or not args.continuation_token or args.plan or args.resume or args.verify:
            raise ValueError('无效的解释器续装参数。')
        directory=continuation_directory(args.continue_after_upgrade)
        plan=json.loads((directory/'plan.json').read_text())
        return execute(plan,directory,continuation_token=args.continuation_token)
    if args.verify:
        from adws_install_acceptance import main as verify
        values=[]
        for name in args.exercise:values += ['--exercise',name]
        for name in args.confirm:values += ['--confirm',name]
        current=state_root()/'current.json'
        directory=None
        if current.exists():
            directory=Path(json.loads(current.read_text())['directory'])
            if not directory.resolve().is_relative_to(state_root().resolve()):raise ValueError('无效的安装记录目录')
            values += ['--output',str(directory/'acceptance.json')]
        code=verify(values)
        if directory and (directory/'progress.json').exists():
            progress=json.loads((directory/'progress.json').read_text())
            # Acceptance must not hide a failed deployment transaction.
            if progress.get('status') in ('pending-acceptance','acceptance-failed','complete'):
                progress['status']={0:'complete',1:'acceptance-failed',2:'pending-acceptance'}[code]
                write_json(directory/'progress.json',progress)
                write_result(json.loads((directory/'plan.json').read_text()),progress,directory,json.loads((directory/'acceptance.json').read_text()))
        return code
    base=state_root()
    if args.resume:
        path=base/'current.json'
        directory=Path(json.loads(path.read_text())['directory'])
        plan=json.loads((directory/'plan.json').read_text())
        if interactive():
            review_plan(plan)
        else:
            print(json.dumps(plan,ensure_ascii=False,indent=2))
        if prompt('复查以上计划并继续？[y/N] ').strip().lower() not in ('y','yes'):return 130
        return execute(plan,directory)
    mode=args.mode
    if mode is None:
        if args.plan:mode='integrate'
        else:
            mode = ('fresh', 'integrate', 'migrate')[choose('安装方案',
                ['全新安装', '已有 Niri 集成 / 重新安装', '从旧机迁移'], default=1)]
    if mode=='migrate' and not args.from_home and not args.plan:args.from_home=text_entry('旧机 HOME 目录（只读来源）：').strip()
    app_choices = {role:getattr(args, role) for role in APP_ROLES}
    if not args.plan:
        choose_applications(mode, app_choices)
    from adws_install_features import selected_features, FEATURE_MANIFEST
    optional_features = ['brightness', 'lock', 'palette']
    skipped = args.skip_feature or []
    if interactive() and not args.plan and args.skip_feature is None:
        enabled = select_targets('可选功能 · 按空格切换，回车确认', optional_features,
                                 initial=optional_features, labels={k: FEATURE_MANIFEST[k]['label'] for k in optional_features})
        skipped = [feature for feature in optional_features if feature not in enabled]
    selected = [feature for feature in selected_features(mode) if feature not in skipped]
    if args.palette_targets and 'palette' in skipped:
        raise ValueError('启用自动配色后才能注册配色同步目标。')
    plan=selected_plan(mode,choices=app_choices,features=selected,migration_source=args.from_home)
    plan['skipped_features'] = skipped
    existing = {name: path_state for name in WAYBAR_DEFAULTS
                if (path_state := config_state(Path(plan['config_home']) / 'waybar' / name)) is not None}
    if existing and not args.plan:
        policy = choose('已有任务栏配置', ['保留现有配置', '备份后覆盖为本版默认配置'],
                        detail='涉及文件：' + '、'.join(existing))
        if policy:
            plan['replace_waybar_defaults'] = existing
    plan['system_upgrade']=args.system_upgrade is True
    if plan['system_upgrade'] and plan['features']['manager']!='pacman':
        raise ValueError('--system-upgrade 当前仅支持 Arch/pacman；其他系统保留原包管理流程。')
    plan['build_fallback']=args.build_fallback
    from adws_install_boot_themes import plan as theme_plan
    plan['theme_plan']=theme_plan(args.login_theme,args.boot_theme)
    plan['login_theme']=args.login_theme;plan['boot_theme']=args.boot_theme
    if plan['theme_plan']['conflicts']:plan['blocking'].append('可选登录／启动主题存在冲突；默认保留系统现状，请审核。')
    plan['autostart']=args.autostart if args.autostart is not None else mode=='fresh'
    if not args.plan:
        if not plan['build_fallback']:plan['build_fallback']=prompt('预编译不匹配时允许源码构建（下载依赖并编译）？[y/N] ').lower() in ('y','yes')
        if args.autostart is None:
            default=plan['autostart'];value=prompt('添加缺失的 Niri 登录启动项（ADWS、输入法和剪贴板等）？已有项目保留启用状态；换目录时受管路径更新会列入计划。'+(' [Y/n] ' if default else ' [y/N] ')).lower()
            plan['autostart']=default if not value else value in ('y','yes')
        from adws_i18n import chinese
        if plan['mirror']=='official' and chinese():
            if prompt('本次构建使用国内镜像 RsProxy（不改现有源）？[y/N] ').lower() in ('y','yes'):plan['mirror']='rsproxy'
        if not shutil.which('niri'):
            plan['niri_method'] = ('repository', 'source')[choose('安装 Niri', ['系统软件源', '官方源码'])]
        if plan['features']['manager']=='pacman' and args.system_upgrade is None:
            default=mode=='fresh'
            value=prompt('完整升级 Arch 系统并补齐依赖？包管理器将展示最终升级列表供确认；不会单独刷新数据库后局部升级。'+(' [Y/n] ' if default else ' [y/N] ')).strip().lower()
            plan['system_upgrade']=default if not value else value in ('y','yes')
    # Finish the complete package/configuration proposal before the single approval.
    from adws_setup import PACKAGES
    manager=plan['features']['manager']
    if plan['build_fallback']:
        from adws_waybar_compat import resolve_waybar
        plan['package_candidates'] += PACKAGES[manager]['build']
        if not resolve_waybar():
            plan['package_candidates'] += PACKAGES[manager]['waybar-build']
    if not shutil.which('niri'):
        from adws_niri_install import BUILD_PACKAGES, SESSION_PACKAGES, installed_packages, package_candidates
        present = installed_packages(manager, SESSION_PACKAGES)
        optional = [name for name in SESSION_PACKAGES if name not in present]
        available = package_candidates(manager, optional)
        plan['skipped_packages'] = [name for name in optional if name not in available]
        plan['package_candidates'] += [name for name in SESSION_PACKAGES if name in present or name in available]
        plan['package_candidates'] += BUILD_PACKAGES[manager] if plan['niri_method']=='source' else ['niri']
    plan['package_candidates']=list(dict.fromkeys(plan['package_candidates']))
    if plan['migration_source']:
        from adws_install_personal import review, text_diff
        from adws_install_migration import CATEGORIES
        categories=args.migration_categories or list(CATEGORIES)
        plan['migration_categories']=categories
        choices=json.loads(args.migration_decisions.read_text()) if args.migration_decisions else {}
        target_xdg={'config':plan['config_home'],'data':plan['data_home']}
        source_xdg={k:v for k,v in [('config',args.source_config_home),('data',args.source_data_home)] if v}
        installed_ids={a['desktop_id'] for a in desktop_inventory()}
        def reviewed():
            return review(plan['migration_source'],plan['home'],categories,decisions=choices,
                installed_desktop_ids=installed_ids,target_xdg=target_xdg,source_xdg=source_xdg,nickname=args.nickname)
        migration=reviewed()
        if not args.plan:
            for row in list(migration['needs_review']):
                key=row['path'];print('需审核：'+key+' — '+row['reason'])
                while True:
                    value = ('k', 'i', 'r', 'd')[choose('迁移文件 · ' + key,
                        ['保留目标', '导入新文件', '备份后覆盖', '查看差异'], detail=row['reason'])]
                    if value=='d':print(text_diff(migration,key));continue
                    if value not in ('i','r','k'):continue
                    choices[key]={'i':'import','r':'replace','k':'keep'}[value];break
                migration=reviewed()
        plan['migration_plan']=migration
        if migration['needs_review']:plan['blocking'].append('迁移文件尚未审核；请按预览选择导入、覆盖或保留。')
    targets=args.palette_targets
    if targets is None and not args.plan and 'palette' not in skipped:
        if interactive():
            targets = select_targets('自动配色同步目标', list(TARGETS))
        else:
            value=prompt('自动配色同步目标（kitty alacritty foot mako dunst icons，以空格分隔；留空保留现状）：').strip()
            targets=value.split() if value else []
    if targets:
        from adws_palette_sync import registration_plan
        if 'icons' in targets and not args.palette_icon_base and not args.plan:
            args.palette_icon_base=text_entry('请输入保留并继承的现有图标主题名称：').strip()
        if 'foot' in targets and not args.foot_shell and not args.plan:
            value = ('', 'bash', 'zsh')[choose('Foot 实时配色', ['保留现有方式', 'bash', 'zsh'])]
            if value not in ('','bash','zsh'):raise ValueError('无效的 Foot Shell 选择')
            args.foot_shell=value or None
        palette=registration_plan(targets,config_home=plan['config_home'],data_home=plan['data_home'],home=plan['home'],
                                  base_icon_theme=args.palette_icon_base,foot_shell=args.foot_shell)
        from adws_install_migration import destination_path
        migrated={str(destination_path(plan['migration_plan'],e).resolve()) for e in plan.get('migration_plan',{}).get('entries',[]) if e.get('action') not in ('keep','skip')}
        for row in palette['files']:
            if row['resolved'] in migrated:palette['conflicts'].append({'path':row['path'],'reason':'迁移和配色注册同时修改此文件；请先完成迁移，再对导入配置启用同步。'})
        plan['palette_plan']=palette
        plan['package_candidates'] += [t if t!='mako' or manager!='apt-get' else 'mako-notifier' for t in targets if t!='icons' and not shutil.which(t)]
        if 'icons' in targets:
            plan['package_candidates'] += {'pacman':['gsettings-desktop-schemas'],'apt-get':['gsettings-desktop-schemas'],'dnf':['gsettings-desktop-schemas']}[manager]
        plan['package_candidates']=list(dict.fromkeys(plan['package_candidates']))
        if palette['conflicts']:plan['blocking'].append('自动配色配置存在冲突；保留原文件，请先审核。')
    from adws_install_source_migration import plan as source_migration_plan
    plan['source_migration']=source_migration_plan(ROOT)
    if plan['source_migration']['conflicts']:
        plan['blocking'].append('更换安装目录存在状态迁移冲突；请审核旧来源和目标文件，不会覆盖另一份桌面布局。')
    from adws_install_topbar_migration import plan as topbar_migration_plan
    foot_hook=str((Path(plan['config_home'])/'adws/palette/foot-hook.sh').resolve())
    palette_writes_hook=any(str(Path(row['path']).resolve())==foot_hook for row in plan.get('palette_plan',{}).get('files',[]))
    plan['topbar_migration']=topbar_migration_plan(plan['config_home'],plan['source_migration'],
        include_foot=not palette_writes_hook)
    if plan['topbar_migration']['conflicts']:
        plan['blocking'].append('顶栏或终端配色入口有未能自动迁移的旧路径；保留自定义内容，请先审核。')
    from adws_layout import desktop_space_relocation_plan
    plan['bottom_library_migration']=desktop_space_relocation_plan(plan['config_home'],plan['source_migration'],home=plan['home'])
    if plan['bottom_library_migration']['conflicts']:
        plan['blocking'].append('底栏吸附模块的旧路径存在迁移冲突；保留自定义库设置，请先审核。')
    from adws_install_niri import relocation_plan
    plan['niri_relocation']=relocation_plan(plan['niri_config_path'],plan['source_migration'])
    if plan['niri_relocation']['conflicts']:
        plan['blocking'].append('旧安装路径的快捷键存在未能自动迁移的引用；保留自定义命令，请先审核。')
    from adws_install_legacy import plan as legacy_plan
    plan['legacy_plan']=legacy_plan(plan['config_home'],niri_path=plan['niri_config_path'],root=ROOT,home=plan['home'])
    if plan['legacy_plan']['conflicts']:
        plan['blocking'].append('旧 MNWS 数据需要明确迁移审核；不会因创建 ADWS 配置目录而将旧设置移到备份后丢弃。')
    from adws_install_session_config import plan as session_plan
    plan['session_plan']=session_plan(plan['config_home'],plan['features'],niri_path=plan['niri_config_path'])
    from adws_launcher import installation_plan as launcher_plan
    plan['launcher_plan']=launcher_plan(plan['config_home'])
    if plan['legacy_plan'].get('launcher_policy'):
        plan['launcher_plan']=plan['legacy_plan']['launcher_policy']
    from adws_commands import plan as command_plan
    plan['command_plan']=command_plan(ROOT)
    command_conflicts = plan['command_plan']['conflicts']
    if command_conflicts:
        replaceable = all(config_state(Path(name)) is not None for name in command_conflicts)
        if not args.plan and replaceable and choose('同名的用户命令',
                ['保留并返回审核', '备份后覆盖这些命令'], detail='\n'.join(command_conflicts)):
            plan['replace_commands'] = {name: config_state(Path(name)) for name in command_conflicts}
            plan['command_plan']['conflicts'] = []
        else:
            plan['blocking'].append('用户命令存在冲突：' + '、'.join(command_conflicts))
    from adws_install_niri import action_commands
    plan['shortcut_plan']=action_commands(ROOT,plan['features'],plan['session_plan']['lock_argv'],require_installed=False)
    addon = 'fcitx5-chinese-addons'
    if addon in plan['package_candidates']:
        needs_pinyin = bool(plan['session_plan'].get('required_data'))
        if needs_pinyin and args.input_addons == 'skip':
            plan['blocking'].append('本次将创建中文拼音配置，需要 fcitx5-chinese-addons。')
        if not needs_pinyin:
            install_addon = args.input_addons == 'install'
            if args.input_addons == 'auto' and interactive() and not args.plan:
                install_addon = bool(choose('可选输入法扩展', ['沿用已有输入方案', '安装 Fcitx 拼音扩展'],
                                            detail='使用 Rime、Mozc 或其他输入方案时可以跳过拼音扩展。'))
            if not install_addon:
                plan['package_candidates'].remove(addon)
                for feature in plan['features']['features']:
                    if addon in feature['packages']:
                        feature['packages'].remove(addon)
                plan['features']['packages'].remove(addon)
                plan.setdefault('skipped_packages', []).append(addon)
    if plan['session_plan']['conflicts']:plan['blocking'].append('输入法环境或用户服务有冲突，请先审核会话配置。')
    if plan['prebuilt']['status']=='integrity-error':plan['blocking'].append('预编译包校验失败，请重新获取可信安装包。')
    elif plan['prebuilt']['status']!='verified' and not plan['build_fallback']:
        plan['blocking'].append('没有匹配的预编译组件；需明确选择允许源码构建。')
    if plan['autostart'] or (plan['source_migration'].get('previous_root')
                             and plan['source_migration']['previous_root']!=plan['source_root']):
        from adws_install_startup import plan as startup_plan
        commands=dict(plan['session_plan']['startup_commands'])
        commands.update({k:plan['session_plan']['session_argv_prefix']+['bash',str(ROOT/'adws'),k,'-s'] for k in ('desktop','taskbar')})
        plan['startup_plan']=startup_plan(plan['config_home'],commands,niri_path=plan['niri_config_path'],
                                          source_migration=plan['source_migration'],add_missing=plan['autostart'])
        if plan['startup_plan']['conflicts'] or plan['startup_plan']['unknown']:
            plan['blocking'].append('自启动发现重复归属或未能解析的来源，请先解决；不会静默删除。')
    from adws_install_package_owners import reviewed_package_owners
    plan['package_owner_plan']=reviewed_package_owners(plan['features'],plan['package_candidates'],plan['config_home'],niri_path=plan['niri_config_path'])
    if plan['package_owner_plan']['conflicts']:
        plan['blocking'].append('软件包自启动归属存在冲突，请先审核；不会覆盖现有用户入口。')
    if manager == 'pacman':
        from adws_niri_install import installed_packages, query
        names = plan['package_candidates']
        satisfied = installed_packages(manager, names)
        missing = [name for name in names if name not in satisfied]
        # pacman -Qq reports the concrete installed name for a virtual target.
        # Query only aliases, since batched output need not preserve input order.
        concrete = set(query(['pacman', '-Qq']).stdout.splitlines())
        aliases = {}
        for name in sorted(satisfied - concrete):
            owner = query(['pacman', '-Qq', '--', name])
            if owner.returncode == 0:
                aliases[name] = owner.stdout.strip()
        plan['package_resolution'] = {'missing': missing, 'providers': aliases,
                                      'satisfied': sorted(satisfied)}
    if plan['system_upgrade']:
        from adws_install_arch_packages import review as package_review
        plan['package_review']=package_review(plan['package_resolution']['missing'])
        if plan['package_review']['status'] == 'failed':
            plan['blocking'].append('软件包事务无法解析：' + ' '.join(
                issue['message'] for issue in plan['package_review']['conflicts']))
        elif not plan['package_review'].get('source_fingerprint'):
            plan['blocking'].append('无法完成软件包升级预览，请先检查报告中的仓库或网络问题。')
    if args.plan:
        print(json.dumps(plan,ensure_ascii=False,indent=2))
        return 0
    review_plan(plan)
    if plan['blocking']:raise ValueError('\n'.join(plan['blocking']))
    if prompt('确认执行以上变更？[y/N] ').strip().lower() not in ('y','yes'):return 130
    plan['approved']=True
    directory=base/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    write_json(directory/'plan.json',plan);write_json(base/'current.json',{'directory':str(directory)})
    return execute(plan,directory)


def run_interactive():
    args = sys.argv[1:]
    while True:
        try:
            return main(args)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            if not interactive() or '--plan' in args or '--verify' in args or '--continue-after-upgrade' in args:
                raise
            print('安装未完成：' + str(error), file=sys.stderr)
            options = ['重新配置安装', '查看完整错误', '退出']
            current = state_root() / 'current.json'
            if current.is_file():
                options.insert(1, '复查并续装上次事务')
            while True:
                action = options[choose('安装未完成', options, detail=str(error))]
                if action == '查看完整错误':
                    import pydoc
                    pydoc.pager(str(error))
                    continue
                if action == '退出':
                    return 1
                args = ['--resume'] if action == '复查并续装上次事务' else []
                break


if __name__=='__main__':
    try:raise SystemExit(run_interactive())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        print('安装未完成：'+str(exc),file=sys.stderr);raise SystemExit(1)
    except (EOFError,KeyboardInterrupt):raise SystemExit(130)
