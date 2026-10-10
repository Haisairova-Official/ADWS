"""AccountsService and timedate1 operations, with credentials kept off argv."""
import ctypes
import ctypes.util
import os
from pathlib import Path
import re
import secrets
import threading
from gi.repository import GLib
from adws_i18n import tr
from adws_native_services import bus_call, properties, text

SERVICE='org.freedesktop.Accounts'
ROOT='/org/freedesktop/Accounts'
USER=SERVICE+'.User'
_CRYPT_LOCK=threading.Lock()


def users():
    paths=bus_call(SERVICE,ROOT,SERVICE,'ListCachedUsers').unpack()[0]
    result=[]
    for path in paths:
        item=properties(SERVICE,path,USER)
        if item.get('Uid',0)>=1000 or item.get('Uid')==os.getuid():
            # Decode and crop in the discovery worker, never in a GTK input handler.
            from adws_account_header import avatar_for_user
            result.append({'path':path,**item,'avatar_png':avatar_for_user(item['Uid'], item.get('IconFile'))})
    return sorted(result,key=lambda item:(item['Uid']!=os.getuid(),item.get('UserName','')))


def password_hash(password):
    if not isinstance(password,str) or not password or len(password)>1024 or '\0' in password:
        raise ValueError(tr('密码不能为空或包含空字符。'))
    library=ctypes.util.find_library('crypt')
    if not library:
        raise RuntimeError(tr('缺少系统密码库 libcrypt。'))
    crypt=ctypes.CDLL(library).crypt
    crypt.argtypes=(ctypes.c_char_p,ctypes.c_char_p);crypt.restype=ctypes.c_char_p
    salt='$6$rounds=100000$'+''.join(secrets.choice('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./') for _ in range(16))+'$'
    with _CRYPT_LOCK:
        hashed=crypt(password.encode(),salt.encode())
        if not hashed or not hashed.startswith(b'$6$'):
            raise RuntimeError(tr('系统无法生成密码散列。'))
        return hashed.decode('ascii')


def create_user(username,name,administrator,password):
    if not isinstance(username,str) or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}',username) or username=='root':
        raise ValueError(tr('用户名须以小写字母开头，只能含小写字母、数字、下划线或短横线。'))
    text(name,128)
    if type(administrator) is not bool:
        raise ValueError('Invalid account type')
    hashed=password_hash(password)
    path=bus_call(SERVICE,ROOT,SERVICE,'CreateUser','(ssi)',(username,name,int(administrator)),timeout=60000).unpack()[0]
    try:
        bus_call(SERVICE,path,USER,'SetPassword','(ss)',(hashed,''),timeout=60000)
    except Exception as error:
        # Never leave a partially created user with an unspecified password.
        try:
            uid=properties(SERVICE,path,USER)['Uid']
            bus_call(SERVICE,ROOT,SERVICE,'DeleteUser','(xb)',(uid,False),timeout=60000)
        except Exception:
            raise RuntimeError(tr('账户已创建，但密码设置失败；请检查此账户状态。')) from error
        raise
    return path


def user_change(expected,action,value):
    path=expected['path']
    if not re.fullmatch(re.escape(ROOT)+r'/User\d+',path):
        raise ValueError('Invalid account path')
    current=properties(SERVICE,path,USER)
    if current.get('Uid')!=expected['Uid']:
        raise RuntimeError(tr('账户信息已变化，请刷新后重试。'))
    uid=current['Uid']
    if action=='delete':
        if uid<1000 or uid==os.getuid() or type(value) is not bool:
            raise ValueError(tr('不能删除根用户、系统账户或当前登录账户。'))
        bus_call(SERVICE,ROOT,SERVICE,'DeleteUser','(xb)',(uid,value),timeout=60000)
    elif action=='password':
        bus_call(SERVICE,path,USER,'SetPassword','(ss)',(password_hash(value),''),timeout=60000)
    elif action=='name':
        bus_call(SERVICE,path,USER,'SetRealName','(s)',(text(value,128),),timeout=60000)
    elif action=='type':
        if uid<1000 or type(value) is not bool or uid==os.getuid() and not value:
            raise ValueError(tr('不能降低当前账户或系统账户的权限。'))
        bus_call(SERVICE,path,USER,'SetAccountType','(i)',(int(value),),timeout=60000)
    elif action=='locked':
        if uid<1000 or uid==os.getuid() or type(value) is not bool:
            raise ValueError(tr('不能禁用当前账户或系统账户。'))
        bus_call(SERVICE,path,USER,'SetLocked','(b)',(value,),timeout=60000)
    elif action=='avatar':
        from PIL import Image
        filename=Path(value).expanduser().resolve(strict=True)
        if not filename.is_file() or filename.stat().st_size>8*1024*1024:
            raise ValueError(tr('头像图片无效或过大。'))
        with Image.open(filename) as image:
            if image.width*image.height>40_000_000:
                raise ValueError(tr('头像图片尺寸过大。'))
            image.verify()
        bus_call(SERVICE,path,USER,'SetIconFile','(s)',(str(filename),),timeout=60000)
    else:
        raise ValueError('Invalid account action')


def timezone_snapshot():
    current=properties('org.freedesktop.timedate1','/org/freedesktop/timedate1','org.freedesktop.timedate1')
    zones=[]
    for filename in ('/usr/share/zoneinfo/zone1970.tab','/usr/share/zoneinfo/zone.tab'):
        try:
            for line in Path(filename).read_text().splitlines():
                if line and not line.startswith('#'):
                    zones.append(line.split('\t')[2])
            break
        except OSError:
            continue
    return {'timezone':current.get('Timezone','UTC'),'ntp':current.get('NTP',False),
            'can_ntp':current.get('CanNTP',False),'zones':sorted(set(['UTC',*zones]))}


def set_timezone(zone):
    if not isinstance(zone,str) or zone not in timezone_snapshot()['zones']:
        raise ValueError(tr('请选择有效时区。'))
    bus_call('org.freedesktop.timedate1','/org/freedesktop/timedate1','org.freedesktop.timedate1','SetTimezone','(sb)',(zone,True),timeout=60000)


def set_ntp(enabled):
    if type(enabled) is not bool:
        raise ValueError('Invalid NTP state')
    bus_call('org.freedesktop.timedate1','/org/freedesktop/timedate1','org.freedesktop.timedate1','SetNTP','(bb)',(enabled,True),timeout=60000)


def edit_user(expected,changes):
    """Validate the entire edit before the first privileged call."""
    if not isinstance(changes,dict) or set(changes)-{'name','type','locked','avatar','password'}:
        raise ValueError('Invalid account fields')
    current=properties(SERVICE,expected['path'],USER)
    if current.get('Uid')!=expected.get('Uid') or any(current.get(key)!=expected.get(key) for key in ('RealName','AccountType','Locked')):
        raise RuntimeError(tr('账户信息已变化，请刷新后重试。'))
    uid=current['Uid'];prepared=[]
    for action,value in changes.items():
        if action=='name':prepared.append(('SetRealName','(s)',(text(value,128),)))
        elif action in ('type','locked'):
            if type(value) is not bool or uid<1000 or uid==os.getuid() and (action=='locked' and value or action=='type' and not value):
                raise ValueError(tr('不能降低当前账户或系统账户的权限。'))
            prepared.append(('SetAccountType' if action=='type' else 'SetLocked','(i)' if action=='type' else '(b)',(int(value) if action=='type' else value,)))
        elif action=='password':prepared.append(('SetPassword','(ss)',(password_hash(value),'')))
        elif action=='avatar':
            from PIL import Image
            filename=Path(value).expanduser().resolve(strict=True)
            if not filename.is_file() or filename.stat().st_size>8*1024*1024:raise ValueError(tr('头像图片无效或过大。'))
            with Image.open(filename) as image:
                if image.width*image.height>40_000_000:raise ValueError(tr('头像图片尺寸过大。'))
                image.verify()
            prepared.append(('SetIconFile','(s)',(str(filename),)))
    if not re.fullmatch(re.escape(ROOT)+r'/User\d+',expected['path']):raise ValueError('Invalid account path')
    originals={'SetRealName':('(s)',(current.get('RealName',''),)),
               'SetAccountType':('(i)',(current.get('AccountType',0),)),
               'SetLocked':('(b)',(current.get('Locked',False),)),
               'SetIconFile':('(s)',(current.get('IconFile',''),))}
    applied=[]
    # Password last: an irreversible successful password change is never followed
    # by a fallible cosmetic operation.
    prepared.sort(key=lambda item:item[0]=='SetPassword')
    try:
        for method,signature,values in prepared:
            bus_call(SERVICE,expected['path'],USER,method,signature,values,timeout=60000);applied.append(method)
    except Exception as error:
        failed=[]
        for method in reversed(applied):
            try:
                signature,values=originals[method]
                bus_call(SERVICE,expected['path'],USER,method,signature,values,timeout=60000)
            except Exception:failed.append(method)
        if failed:raise RuntimeError(tr('账户修改未完全恢复，请刷新检查此账户。')) from error
        raise


def locale_snapshot():
    from adws_system_pages import available_locales
    data=properties('org.freedesktop.locale1','/org/freedesktop/locale1','org.freedesktop.locale1')
    values=dict(item.split('=',1) for item in data.get('Locale',[]) if '=' in item)
    return {'values':values,'locales':available_locales()}


def set_locales(expected,changes):
    from adws_system_pages import locale_key
    if not isinstance(changes,dict) or set(changes)!={'LANG','LC_TIME','LC_NUMERIC'}:raise ValueError('Invalid locale fields')
    current=locale_snapshot();valid={locale_key(v) for v in current['locales']}
    if current['values']!=expected['values']:raise RuntimeError(tr('地区设置已被修改，请刷新后重试。'))
    if any(not isinstance(v,str) or locale_key(v) not in valid for v in changes.values()):raise ValueError(tr('请选择系统中已安装的语言。'))
    values={**current['values'],**changes}
    # LC_ALL overrides all individual categories. Retaining it would make the
    # newly selected formats appear to have no effect.
    values.pop('LC_ALL',None)
    bus_call('org.freedesktop.locale1','/org/freedesktop/locale1','org.freedesktop.locale1','SetLocale','(asb)',([key+'='+value for key,value in values.items()],True),timeout=60000)


def set_time(value):
    from datetime import datetime
    try:
        instant=datetime.fromisoformat(value)
        if instant.tzinfo is None or not 1970<=instant.year<=2100:raise ValueError()
    except (TypeError,ValueError):raise ValueError(tr('请输入带时区的日期时间，例如 2026-10-04T12:00:00+08:00。'))
    state=timezone_snapshot()
    if state['ntp']:raise ValueError(tr('请先关闭自动同步系统时间，再手动设置时间。'))
    bus_call('org.freedesktop.timedate1','/org/freedesktop/timedate1','org.freedesktop.timedate1','SetTime','(xbb)',(int(instant.timestamp()*1_000_000),False,True),timeout=60000)
