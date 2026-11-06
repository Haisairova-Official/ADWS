"""Capture/preview runtime checks. No display, audio devices or capture sessions opened."""
import json
import shutil
import subprocess
import sys
from adws_i18n import tr

PREVIEW_ELEMENTS=('pipewiresrc','queue','videorate','videoconvert','videoscale','pngenc','appsink')
PROBE='''import json,gi
gi.require_version('Gst','1.0')
gi.require_version('GstApp','1.0')
from gi.repository import Gst,GstApp
Gst.init(None)
print(json.dumps([name for name in %r if Gst.ElementFactory.find(name) is None]))
''' % (PREVIEW_ELEMENTS,)


def missing_dependencies():
    missing={}
    capture=[name for name in ('grim','slurp','wl-copy','wl-paste') if not shutil.which(name)]
    if capture:missing['capture']=capture
    preview=[]
    if not shutil.which('pipewire'):preview.append('PipeWire')
    # Preserve an existing session manager rather than replacing it.
    if not any(shutil.which(name) for name in ('wireplumber','pipewire-media-session')):
        preview.append('PipeWire session manager')
    try:
        result=subprocess.run([sys.executable,'-c',PROBE],capture_output=True,text=True,timeout=15)
        if result.returncode:
            detail=(result.stderr.strip().splitlines() or ['Gst / GstApp unavailable'])[-1]
            preview.append('GStreamer Python / GstApp: '+detail)
        else:
            elements=json.loads(result.stdout)
            if not isinstance(elements,list) or not all(isinstance(name,str) for name in elements):
                raise ValueError('Invalid GStreamer dependency probe')
            preview.extend(elements)
    except (OSError,ValueError,subprocess.TimeoutExpired) as error:
        preview.append('GStreamer: '+str(error))
    if preview:missing['preview']=preview
    return missing


def messages(missing):
    labels={'capture':tr('截图／取色依赖不完整：'),'preview':tr('窗口预览依赖不完整：')}
    return [labels[key]+', '.join(values) for key,values in missing.items()]


def install_groups(missing):
    groups=list(missing)
    if 'PipeWire session manager' in missing.get('preview',[]):groups.append('preview-session')
    return groups
