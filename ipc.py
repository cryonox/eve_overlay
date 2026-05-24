"""Tiny file-based IPC between the supervisor (tray) and the window children.

The supervisor writes control.json (desired overlay/module state); children poll
it each frame and apply it. Writes are atomic via os.replace.
"""
import json
import os
from config import get_base_path

CONTROL_FILE = 'control.json'


def _path(name):
    return get_base_path() / name


def write_json(name, data):
    p = _path(name)
    tmp = p.with_name(p.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    os.replace(tmp, p)


def read_json(name, default=None):
    try:
        with open(_path(name), 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {} if default is None else default


def mtime(name):
    try:
        return _path(name).stat().st_mtime
    except OSError:
        return 0.0
