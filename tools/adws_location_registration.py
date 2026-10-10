"""Hidden application identity for GeoClue, with ownership-safe removal."""
import os
from pathlib import Path

DESKTOP_ID='org.adws.Sidebar'
REGISTRATION='[Desktop Entry]\nType=Application\nName=ADWS Weather\nName[zh_CN]=ADWS 天气\nExec=adws sidebar\nIcon=weather-few-clouds-symbolic\nNoDisplay=true\nX-Geoclue-Reason=Show local weather and a coastal sea-level forecast.\nX-Geoclue-Reason[zh_CN]=显示当地天气与沿海潮位趋势。\n'


def registration_path():
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'applications'/f'{DESKTOP_ID}.desktop'


def register_location_app():
    path=registration_path()
    if path.exists() or path.is_symlink():
        if path.is_symlink() or path.read_text()!=REGISTRATION:raise ValueError('Location application registration conflicts')
        return DESKTOP_ID
    from adws_atomic import stage
    temporary=stage(path,REGISTRATION.encode(),0o644)
    try:
        # Do not overwrite an entry created concurrently by another application.
        try:os.link(temporary,path)
        except FileExistsError:
            if path.is_symlink() or path.read_text()!=REGISTRATION:raise
    finally:temporary.unlink(missing_ok=True)
    return DESKTOP_ID


def remove_location_registration():
    path=registration_path()
    if path.is_file() and not path.is_symlink() and path.read_text()==REGISTRATION:path.unlink()
