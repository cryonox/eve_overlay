import yaml
from pathlib import Path
import sys
import threading
from loguru import logger

_write_lock = threading.Lock()


class AttrDict(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except (KeyError, RecursionError):
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    def _get_nested(self, key_path):
        obj = self
        for p in key_path.split('.'):
            if obj is None:
                return None
            obj = obj.get(p) if isinstance(obj, dict) else None
        return obj

    def _to_dict(self, obj=None):
        obj = obj if obj is not None else self
        if isinstance(obj, AttrDict):
            return {k: self._to_dict(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._to_dict(v) for v in obj]
        return obj

    def write(self, keys, filepath):
        from functools import reduce
        base_path = get_base_path()
        fpath = base_path / filepath
        
        with _write_lock:
            existing = {}
            if fpath.exists():
                with open(fpath, 'r') as f:
                    existing = yaml.safe_load(f) or {}
            
            def set_nested(obj, key_path, val):
                parts = key_path.split('.')
                for p in parts[:-1]:
                    obj = obj.setdefault(p, {})
                obj[parts[-1]] = val
            
            for key in keys:
                val = self._get_nested(key)
                if val is not None:
                    set_nested(existing, key, self._to_dict(val))
            
            def represent_list(dumper, data):
                return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)
            
            yaml.add_representer(list, represent_list)
            with open(fpath, 'w') as f:
                yaml.dump(existing, f, default_flow_style=False, indent=2)


def dict2attrdict(dictionary):
    ret = AttrDict()
    for key, value in dictionary.items():
        if isinstance(value, dict):
            ret[key] = dict2attrdict(value)
        elif isinstance(value, list):
            ret[key] = []
            for v in value:
                if isinstance(v, dict):
                    ret[key].append(dict2attrdict(v))
                else:
                    ret[key].append(v)
        else:
            ret[key] = value
    return ret


def create_default_config(fpath):
    default_config = {
        'cache': 'cache',
        'logging': {
            'enabled': True,
            'level': 'INFO'
        },
        'dscan': {
            'enabled': True,
            'ignore': [],
            'hotkey_overlay': 'alt+shift+t',
            'hotkey_clickthrough': 'alt+shift+c',
            'hotkey_bg': 'alt+shift+b',
            'hotkey_mode': 'alt+shift+m',
            'hotkey_clear_cache': 'alt+shift+e',
            'font_scale': 0.5,
            'font_thickness': 1,
            'transparency': 180,
            'transparency_color': [64, 64, 64],
            'bg_color': [25, 25, 25],
            'timeout': 15,
            'diff_timeout': 60,
            'group_rect_width': 3
        }
    }

    def represent_list(dumper, data):
        return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)

    yaml.add_representer(list, represent_list)

    with open(fpath, 'w') as f:
        yaml.dump(default_config, f, default_flow_style=False, indent=2)
    print(f"Created default config at {fpath}")


def load_config(fpath):
    fpath = Path(fpath)
    if not fpath.exists():
        return None
    with open(fpath, "r") as stream:
        try:
            return dict2attrdict(yaml.safe_load(stream))
        except Exception:
            return None


def substitute(config, rules):
    for k, v in config.items():
        if type(v) == str:
            for kk, vv in rules.items():
                if kk in v:
                    config[k] = v.replace(kk, vv)
        elif type(v) == AttrDict:
            config[k] = substitute(v, rules)
    return config


def merge_dict(base, update):
    for k, v in update.items():
        if isinstance(v, AttrDict) and isinstance(base.get(k), AttrDict):
            base[k] = merge_dict(base[k], v)
        else:
            base[k] = v
    return base


def configure_logger(cfg):
    from loguru import logger
    logger.remove()
    level = cfg.logging.get('level', 'INFO').upper()
    logger.add(sys.stderr, level=level)


def attrdict2dict(obj):
    if isinstance(obj, AttrDict):
        return {k: attrdict2dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [attrdict2dict(v) for v in obj]
    return obj


def get_nested(obj, key_path):
    parts = key_path.split('.')
    for p in parts:
        if obj is None:
            return None
        obj = obj.get(p) if isinstance(obj, dict) else None
    return obj


def set_nested(obj, key_path, val):
    parts = key_path.split('.')
    for p in parts[:-1]:
        obj = obj.setdefault(p, {})
    obj[parts[-1]] = val


def write(keys, filepath):
    global C
    base_path = get_base_path()
    fpath = base_path / filepath
    
    with _write_lock:
        existing = {}
        if fpath.exists():
            with open(fpath, 'r') as f:
                existing = yaml.safe_load(f) or {}
        
        for key in keys:
            val = get_nested(C, key)
            if val is not None:
                set_nested(existing, key, attrdict2dict(val))
        
        def represent_list(dumper, data):
            return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)
        
        yaml.add_representer(list, represent_list)
        with open(fpath, 'w') as f:
            yaml.dump(existing, f, default_flow_style=False, indent=2)


def get_base_path():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def load_all_configs():
    base_path = get_base_path()
    main_cfg_path = base_path / 'config.yaml'
    
    if not main_cfg_path.exists():
        create_default_config(main_cfg_path)
    
    cfg = load_config(main_cfg_path)
    if cfg is None:
        print('config.yaml is empty.')
        create_default_config(main_cfg_path)
        cfg = load_config(main_cfg_path)
    
    extra_files = sorted(base_path.glob('config.*.yaml'))
    for fpath in extra_files:
        extra_cfg = load_config(fpath)
        if extra_cfg is not None:
            cfg = merge_dict(cfg, extra_cfg)
            logger.info(f"Merged config from {fpath.name}")
    
    rules = {'$pwd': str(base_path)}
    cfg = substitute(cfg, rules)
    configure_logger(cfg)
    return cfg


C = load_all_configs()
logger.info(C)
