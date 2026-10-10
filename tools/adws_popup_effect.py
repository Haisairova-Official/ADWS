"""Optional native blur-region control; older libraries/compositors keep GTK fallback."""
import ctypes
from functools import lru_cache
import os
from pathlib import Path


def library_paths():
    return [Path.home()/'.local/lib/waybar/libwaybar-space.so',
            Path(__file__).resolve().parents[1]/'src/niri-desktop-layer/integration/libwaybar-space.so']


@lru_cache(maxsize=1)
def load_library():
    for path in library_paths():
        try:
            library = ctypes.CDLL(str(path))
            library.adws_popup_effect_create.argtypes = [ctypes.c_void_p]
            library.adws_popup_effect_create.restype = ctypes.c_void_p
            library.adws_popup_effect_region.argtypes = [ctypes.c_void_p]+[ctypes.c_int]*5
            library.adws_popup_effect_region.restype = None
            library.adws_popup_effect_destroy.argtypes = [ctypes.c_void_p]
            library.adws_popup_effect_destroy.restype = None
            return library
        except (OSError, AttributeError):
            continue
    return None


class PopupEffect:
    def __init__(self, window):
        self.library = None
        self.handle = None
        self.region = None
        window.connect('realize', self.realize)
        window.connect('map', self.realize)
        window.connect('unmap', self.release)
        window.connect('unrealize', self.release)
        window.connect('destroy', self.release)

    def realize(self, window):
        if self.handle or not os.environ.get('WAYLAND_DISPLAY'): return
        native = window.get_window()
        if not native or 'Wayland' not in type(native).__name__: return
        library = load_library()
        if library is None: return
        pointer = ctypes.pythonapi.PyCapsule_GetPointer
        pointer.argtypes = [ctypes.py_object, ctypes.c_char_p]; pointer.restype = ctypes.c_void_p
        self.library = library
        self.handle = library.adws_popup_effect_create(pointer(native.__gpointer__, None))

    def update(self, x, y, width, height, radius):
        if not self.handle: return
        region = tuple(map(int, (x, y, width, height, radius)))
        if region != self.region:
            self.library.adws_popup_effect_region(self.handle, *region)
            self.region = region

    def release(self, *_):
        if self.handle:
            self.library.adws_popup_effect_destroy(self.handle)
            self.handle = None
        self.region = None
