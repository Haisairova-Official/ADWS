#!/usr/bin/env python3
"""Build a standalone, stdlib-only verified-download installer entry (.pyz)."""
import argparse
import hashlib
from pathlib import Path
import shutil
import tempfile
import zipapp

ROOT=Path(__file__).resolve().parents[1]
FILES=(
    'tools/adws_bootstrap.py','tools/adws_download.py','tools/adws_update.py','tools/adws_upgrade.py','tools/adws_prebuilt.py','tools/adws_i18n.py',
    'src/niri-desktop-layer/desktop_layer/__init__.py','src/niri-desktop-layer/desktop_layer/i18n.py',
    'language/en.json','language/zh.json',
)


def build(output,root=ROOT):
    output=Path(output);root=Path(root)
    # The shared updater's translations use real paths. Unpack only this fixed
    # allowlist into a temporary directory, then reuse modules unchanged.
    main='''import sys, tempfile, zipfile
from pathlib import Path
if sys.version_info < (3,11):
    raise SystemExit('Python 3.11+ is required')
FILES = %r
with tempfile.TemporaryDirectory(prefix='adws-bootstrap-runtime-') as temporary:
    root=Path(temporary)
    with zipfile.ZipFile(sys.argv[0]) as bundle:
        for name in FILES:
            info=bundle.getinfo(name)
            if info.file_size > 4*1024*1024: raise SystemExit('Invalid bootstrap runtime')
            path=root/name; path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(bundle.read(name))
    sys.path.insert(0,str(root/'tools'))
    from adws_bootstrap import main
    try: raise SystemExit(main())
    except (OSError,ValueError,RuntimeError) as error: raise SystemExit('Bootstrap incomplete: '+str(error))
    except (EOFError,KeyboardInterrupt): raise SystemExit(130)
''' % (FILES,)
    with tempfile.TemporaryDirectory(prefix='adws-bootstrap-build-') as temporary:
        stage=Path(temporary)
        for name in FILES:
            source=root/name
            if not source.is_file():raise ValueError('Missing bootstrap module: '+name)
            target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        (stage/'__main__.py').write_text(main)
        output.parent.mkdir(parents=True,exist_ok=True)
        temporary_output=output.with_name(output.name+'.new')
        try:
            zipapp.create_archive(stage,target=temporary_output,interpreter='/usr/bin/env python3',compressed=True)
            temporary_output.replace(output)
        finally:temporary_output.unlink(missing_ok=True)
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix+'.sha256').write_text(digest+'  '+output.name+'\n')
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist/adws-bootstrap.pyz')
    args=parser.parse_args();print(build(args.output))

if __name__=='__main__':main()
