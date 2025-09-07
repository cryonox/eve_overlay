import yaml
from pathlib import Path
import sys
from rich import print


class AttrDict(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except (KeyError, RecursionError):
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


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
        'logging': {
            'enabled': True
        },
        'dscan': {
            'enabled': True,
            'ignore_alliances': [],
            'ignore_corps': [],
            'hotkey_transparency': 'alt+shift+f',
            'transparency_on': True,
            'font_scale': 0.5,
            'font_thickness': 1,
            'transparency': 180,
            'transparency_color': [64, 64, 64],
            'bg_color': [25, 25, 25],
            'timeout': 15
        }
    }

    def represent_list(dumper, data):
        return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)

    yaml.add_representer(list, represent_list)

    with open(fpath, 'w') as f:
        yaml.dump(default_config, f, default_flow_style=False, indent=2)
    print(f"Created default config at {fpath}")


def load_config(fpath=None):
    if fpath is None:
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller executable
            base_path = Path(sys.executable).parent
        else:
            # Running as script
            base_path = Path(__file__).resolve().parent
        fpath = base_path / 'config.yaml'
    else:
        fpath = Path(fpath)

    if not fpath.exists():
        create_default_config(fpath)

    with open(fpath, "r") as stream:
        try:
            c = dict2attrdict(yaml.safe_load(stream))
            return c
        except Exception as ex:
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


C = None
if C is None:
    C = load_config()
    if C is None:
        print('config.yaml is empty.')
        create_default_config('config.yaml')
        C = load_config()
    if Path('config.private.yaml').exists():
        Cp = load_config('config.private.yaml')
        if Cp is not None:
            C = merge_dict(C, Cp)

    rules = {}
    cur_path = Path(__file__).resolve().parent
    rules['$pwd'] = str(cur_path)
    C = substitute(C, rules)
