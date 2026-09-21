"""Expose the shared desktop/CLI translation implementation to tools."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/niri-desktop-layer'))
from desktop_layer.i18n import chinese, tr, message, prepare_gtk_language  # noqa: E402,F401

if __name__ == '__main__':
    print(tr(sys.argv[1]))
