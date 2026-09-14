"""Validated configuration; reading it never modifies desktop configuration."""
from .i18n import tr as _tr
from dataclasses import dataclass, fields, field
from pathlib import Path
import os
import tomllib


@dataclass
class Config:
    directory: str = ""
    monitor: str = "primary"
    icon_size: int = 48
    cell_width: int = 112
    cell_height: int = 104
    columns: int = 0
    overview_blur: int = 5
    margin: int = 18
    font_size: int = 10
    font_family: str = "Noto Sans CJK SC"
    show_hidden: bool = False
    single_click: bool = False
    sort_by: str = "name"
    sort_descending: bool = False
    folders_first: bool = True
    visibility_marker: str = field(default_factory=lambda: str(Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "desktop-hidden"))


def config_path():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "niri-desktop-layer/config.toml"


def state_path():
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "niri-desktop-layer/layout.json"


def load_config(path=None):
    path = Path(path) if path else config_path()
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    defaults = Config()
    allowed = {f.name for f in fields(Config)}
    unknown = data.keys() - allowed
    if unknown:
        raise ValueError(_tr('未知配置项: ') + ", ".join(sorted(unknown)))
    for key, value in data.items():
        if type(value) is not type(getattr(defaults, key)):
            raise ValueError(''.join([f'{key}', _tr(' 的类型应为 '), f'{type(getattr(defaults, key)).__name__}']))
    cfg = Config(**data)
    return validate_config(cfg)


def validate_config(cfg):
    if cfg.sort_by not in ("name", "type", "size", "modified"):
        raise ValueError(_tr('sort_by 必须为 name、type、size 或 modified'))
    for key, low, high in [("icon_size", 24, 96), ("cell_width", 80, 240),
                           ("cell_height", 80, 240), ("columns", 0, 24), ("overview_blur", 0, 20), ("margin", 0, 160), ("font_size", 8, 20)]:
        if not low <= getattr(cfg, key) <= high:
            raise ValueError(''.join([f'{key}', _tr(' 必须在 '), f'{low}', '～', f'{high}', _tr(' 之间')]))
    if cfg.cell_width < cfg.icon_size + 16 or cfg.cell_height < cfg.icon_size + cfg.font_size * 3 + 14:
        raise ValueError(_tr('图标格子太小，请增大 cell_width / cell_height'))
    if not cfg.monitor:
        raise ValueError(_tr('monitor 不能为空'))
    if not cfg.font_family.strip():
        raise ValueError(_tr('font_family 不能为空'))
    return cfg
