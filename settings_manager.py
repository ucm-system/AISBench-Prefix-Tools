#!/usr/bin/env python3
"""Persist small user preferences such as UI language."""

import json
import os
from pathlib import Path
from typing import Dict


DEFAULT_SETTINGS = {
    "language": "zh",
}


def _settings_dir() -> Path:
    app_data = os.environ.get("APPDATA")
    if app_data:
        return Path(app_data) / "AISBenchPrefixTools"
    return Path.home() / ".config" / "AISBenchPrefixTools"


def settings_path() -> Path:
    return _settings_dir() / "settings.json"


def load_settings() -> Dict[str, object]:
    path = settings_path()
    if not path.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return DEFAULT_SETTINGS.copy()
        settings = DEFAULT_SETTINGS.copy()
        settings.update(data)
        return settings
    except (OSError, json.JSONDecodeError):
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: Dict[str, object]) -> bool:
    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False
