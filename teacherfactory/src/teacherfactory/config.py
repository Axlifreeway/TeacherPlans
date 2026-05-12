"""
Загрузчик конфигурации.

Читает config.default.toml, затем мержит поверх config.local.toml (если есть).
config.local.toml находится в .gitignore — создай его под своё железо.
"""

import tomllib
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent  # teacherfactory/


def _load() -> dict:
    default_path = _ROOT / "config.default.toml"
    local_path = _ROOT / "config.local.toml"

    with default_path.open("rb") as f:
        cfg = tomllib.load(f)

    if local_path.exists():
        with local_path.open("rb") as f:
            overrides = tomllib.load(f)
        for section, values in overrides.items():
            if section in cfg and isinstance(cfg[section], dict):
                cfg[section].update(values)
            else:
                cfg[section] = values

    return cfg


CONFIG = _load()
