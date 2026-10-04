"""Narrow privileged writer for ADWS-owned logind policy; no live service restart."""
import json
import os
from pathlib import Path
import tempfile

TARGET=Path('/etc/systemd/logind.conf.d/90-adws-power.conf')
ACTIONS={'ignore','poweroff','reboot','halt','suspend','hibernate','hybrid-sleep','suspend-then-hibernate','lock'}
FIELDS={'HandlePowerKey','HandleLidSwitch','HandleLidSwitchExternalPower','HandleLidSwitchDocked'}
HEADER='# Managed by ADWS system settings\n'


def validate(data):
    if not isinstance(data,dict) or set(data)!=FIELDS or any(value not in ACTIONS for value in data.values()):
        raise ValueError('Invalid logind policy')
    return HEADER+'[Login]\n'+''.join(key+'='+data[key]+'\n' for key in sorted(FIELDS))


def write(data):
    content=validate(data)
    if os.geteuid()!=0:raise PermissionError('Administrator authorization required')
    folder=TARGET.parent
    if folder.is_symlink() or TARGET.is_symlink():raise ValueError('Refusing a symlink policy path')
    folder.mkdir(mode=0o755,parents=True,exist_ok=True)
    if TARGET.exists() and not TARGET.read_text().startswith(HEADER):raise ValueError('Existing policy is not owned by ADWS')
    fd,name=tempfile.mkstemp(prefix='.adws-',dir=folder)
    try:
        with os.fdopen(fd,'w') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
        os.chmod(name,0o644);os.replace(name,TARGET)
    finally:Path(name).unlink(missing_ok=True)


if __name__=='__main__':
    import sys
    if sys.argv[1:]:raise SystemExit('Unsupported arguments')
    raw=sys.stdin.buffer.read(4097)
    if len(raw)>4096:raise SystemExit('Policy too large')
    write(json.loads(raw))
