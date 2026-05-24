"""Entry point. Dispatches by --module:

    (none) / supervisor  -> tray supervisor (spawns the window children)
    dscan                -> dscan analyzer overlay window
    dps                  -> dps meter overlay window

The supervisor relaunches this same exe with --module to start each child.
"""
import os
import sys


def _parse_module():
    args = sys.argv[1:]
    if '--module' in args:
        i = args.index('--module')
        if i + 1 < len(args):
            return args[i + 1]
    return 'supervisor'


def main():
    module = _parse_module()
    # Set before importing config so the logger picks the per-module log file.
    os.environ['EVE_OVERLAY_MODULE'] = module

    if module == 'dscan':
        from dscan_analyzer import main as run
    elif module == 'dps':
        from dps_meter import main as run
    else:
        from supervisor import main as run
    run()


if __name__ == '__main__':
    main()
