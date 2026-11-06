#!/usr/bin/env python3
"""Remove ADWS only from an existing isolated installer fixture and verify scope."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess

CASE=r'''
import hashlib,json,os,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/opt/adws/tools')
from adws_install_startup import audit
report=Path('/opt/adws/uninstall-evidence');report.mkdir(exist_ok=True)
config=Path(os.environ['XDG_CONFIG_HOME']);niri=config/'niri/config.kdl'
# Add documented user-style dependencies to exercise purge preservation, not just
# the default install's possibly empty palette/output configuration.
display=config/'adws/displays/validation-output.kdl';display.parent.mkdir(parents=True,exist_ok=True);display.write_text('// User-owned output choices survive uninstall\n')
with niri.open('a') as output:output.write('\ninclude '+json.dumps(str(display))+'\n')
palette=config/'adws/palette';palette.mkdir(exist_ok=True);(palette/'validation-terminal.conf').write_text('# User terminal includes this palette\n')
preserve=[config/'mimeapps.list',config/'adws/default-terminal.json',config/'adws/niri-session.kdl',config/'adws/palette-sync.json',*(config/'adws/palette').rglob('*')]
preserve.append(display)
system_files=[Path('/etc/locale.conf'),Path('/etc/environment')]
def hashes(paths):return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
before=hashes(system_files+preserve);owners_before=audit(config)['owners']
(report/'before.kdl').write_bytes(niri.read_bytes())
process=subprocess.run(['bash','/opt/adws/adws','--uninstall'],input='y\nn\n',text=True,capture_output=True,timeout=60)
(report/'stdout').write_text(process.stdout);(report/'stderr').write_text(process.stderr)
(report/'after.kdl').write_bytes(niri.read_bytes())
owners=audit(config)['owners'];system_kept=all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in before.items())
shared_kept=all(owners[k]==owners_before[k] or [r['argv'] for r in owners[k]]==[r['argv'] for r in owners_before[k]] for k in ('clipboard-text','clipboard-image','notifications','input-method'))
validate=subprocess.run(['niri','validate','-c',str(niri)],capture_output=True,text=True,timeout=20)
result={'environment':'root-mapped Arch fixture; not normal user login','exit':process.returncode,'niri_validate_exit':validate.returncode,
        'adws_autostarts_removed':not owners['desktop'] and not owners['taskbar'],
        'shared_startups_retained':shared_kept,'system_and_default_associations_retained':system_kept,
        'taskbar_library_removed':not (Path.home()/'.local/lib/waybar/libniri_taskbar.so').exists(),
        'command_link_removed':not (Path.home()/'.local/bin/adws').is_symlink(),
        'niri_validation_detail':validate.stderr.strip()[-1000:]}
result['status']='passed' if process.returncode==validate.returncode==0 and all(result[k] for k in ('adws_autostarts_removed','shared_startups_retained','system_and_default_associations_retained','taskbar_library_removed','command_link_removed')) else 'failed'
(report/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(0 if result['status']=='passed' else 1)
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs',type=Path,required=True)
    parser.add_argument('--installer-snapshot',type=Path,required=True)
    args=parser.parse_args();rootfs=args.rootfs.resolve();stage=args.installer_snapshot.resolve()
    if stage.parent!=rootfs.parent/'installer-cases':raise ValueError('Expected isolated installer snapshot')
    data=json.loads((stage/'lifecycle-evidence/result.json').read_text());home=data['home']
    if not home.startswith('/tmp/adws-install-fixtures/'):raise ValueError('Expected private fixture HOME')
    spec=importlib.util.spec_from_file_location('h',Path(__file__).with_name('check_install_arch_clean.py'))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    command=helper.container_command(rootfs,stage,['python','-c',CASE]);index=command.index(str(stage));command[index-1]='--bind'
    index=command.index('HOME=/root');command[index]='HOME='+home
    command[index:index]=['XDG_CONFIG_HOME='+home+'/.config','XDG_DATA_HOME='+home+'/.local/share',
                         'XDG_STATE_HOME='+home+'/.local/state','XDG_CACHE_HOME='+home+'/.cache','USER=adws-fixture','LOGNAME=adws-fixture']
    return subprocess.run(command,timeout=90).returncode


if __name__=='__main__':raise SystemExit(main())
