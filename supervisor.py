"""Supervisor process: owns the single tray icon and the global overlay hotkeys,
spawns/stops the window child processes (dscan, dps), and fans tray/hotkey
actions out to both via control.json. It has no window of its own so disabling a
module can never take the tray down.
"""
import os
import subprocess
import sys
import time

import pystray
from global_hotkeys import register_hotkeys, start_checking_hotkeys, stop_checking_hotkeys
from loguru import logger

import ipc
import console_log
from config import C, dict2attrdict, get_base_path
from tray import TrayManager

MODULES = ('dscan', 'dps')


class Supervisor:
    def __init__(self):
        if 'dps' not in C:
            C.dps = dict2attrdict({'enabled': True, 'ignore': []})
        ui = C.get('overlay_state', {})
        self.overlay = bool(ui.get('overlay', False))
        self.clickthrough = bool(ui.get('clickthrough', False))
        self.text_bg = bool(ui.get('text_bg', False))
        # Opacity is shared by both windows and lives here (driven from the tray).
        self.opacity_pct = int(ui.get('transparency_pct', 70))

        self.modules = {
            'dscan': bool(C.dscan.get('enabled', True)),
            'dps': bool(C.get('dps', {}).get('enabled', True)),
        }
        self.monitor_clipboard = True
        self.corp_count = 0
        self.dps_show_all = 0

        self.seq = 0
        self.procs = {m: None for m in MODULES}
        self._quit = False

        self.tray = TrayManager(self._build_menu)

    # ---- control / persistence ----------------------------------------

    def _write_control(self):
        self.seq += 1
        ipc.write_json(ipc.CONTROL_FILE, {
            'seq': self.seq,
            'overlay': self.overlay,
            'clickthrough': self.clickthrough,
            'text_bg': self.text_bg,
            'transparency': round(self.opacity_pct / 100 * 255),
            'modules': dict(self.modules),
            'dscan': {'monitor_clipboard': self.monitor_clipboard,
                      'corp_toggle': self.corp_count},
            'dps': {'show_all': self.dps_show_all},
        })

    def _persist_overlay(self):
        C.overlay_state = dict2attrdict({
            'overlay': self.overlay,
            'clickthrough': self.clickthrough,
            'text_bg': self.text_bg,
            'transparency_pct': self.opacity_pct,
        })
        try:
            C.write(['overlay_state'], 'config.state.yaml')
        except Exception:
            logger.exception("persist overlay_state failed")

    def _persist_modules(self):
        C.dscan.enabled = self.modules['dscan']
        C.dps.enabled = self.modules['dps']
        try:
            C.write(['dscan.enabled', 'dps.enabled'], 'config.state.yaml')
        except Exception:
            logger.exception("persist modules failed")

    # ---- child processes ----------------------------------------------

    def _child_args(self, module):
        if getattr(sys, 'frozen', False):
            return [sys.executable, '--module', module]
        return [sys.executable, str(get_base_path() / 'eve_overlay.py'), '--module', module]

    def _spawn(self, module):
        p = self.procs.get(module)
        if p and p.poll() is None:
            return
        env = os.environ.copy()
        env['EVE_OVERLAY_MODULE'] = module
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self.procs[module] = subprocess.Popen(
            self._child_args(module), env=env, creationflags=flags,
            cwd=str(get_base_path()))
        logger.info(f"spawned {module} pid={self.procs[module].pid}")

    def _terminate(self, module):
        p = self.procs.get(module)
        if p and p.poll() is None:
            # the child exits itself once it sees modules[module]=False; wait,
            # then hard-kill as a fallback.
            try:
                p.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                logger.warning(f"{module} didn't exit; terminating")
                p.terminate()
        self.procs[module] = None

    def _supervise(self):
        for m in MODULES:
            if not self.modules[m]:
                continue
            p = self.procs.get(m)
            if p is None or p.poll() is not None:
                logger.warning(f"{m} not running; (re)spawning")
                self._spawn(m)

    # ---- tray menu -----------------------------------------------------

    def _build_menu(self):
        items = [
            pystray.MenuItem('Overlay', lambda i, it: self.toggle_overlay(),
                             checked=lambda it: self.overlay),
            pystray.MenuItem('Click-through', lambda i, it: self.toggle_clickthrough(),
                             checked=lambda it: self.clickthrough),
            pystray.MenuItem('Show background', lambda i, it: self.toggle_text_bg(),
                             checked=lambda it: self.text_bg),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Opacity:', None, enabled=False),
        ]
        # Flat opacity levels; clicking one re-opens the menu so several can be
        # tried quickly (see TrayManager.request_reopen).
        items += [
            pystray.MenuItem(
                f"  {lvl}%", (lambda p: (lambda i, it: self.set_opacity(p)))(lvl),
                checked=(lambda p: (lambda it: self.opacity_pct == p))(lvl),
                radio=True)
            for lvl in (100, 90, 80, 70, 60, 50)
        ]
        items += [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Dscan', lambda i, it: self.toggle_module('dscan'),
                             checked=lambda it: self.modules['dscan']),
            pystray.MenuItem('DPS meter', lambda i, it: self.toggle_module('dps'),
                             checked=lambda it: self.modules['dps']),
            pystray.Menu.SEPARATOR,
        ]
        if self.modules['dscan']:
            items += [
                pystray.MenuItem('Monitor clipboard', lambda i, it: self.toggle_monitor(),
                                 checked=lambda it: self.monitor_clipboard),
                pystray.MenuItem('Corp mode (toggle)', lambda i, it: self.corp_toggle()),
                pystray.Menu.SEPARATOR,
            ]
        if self.modules['dps']:
            items.append(pystray.MenuItem('Show all chars', lambda i, it: self.show_all()))
            items.append(pystray.Menu.SEPARATOR)
        items += [
            pystray.MenuItem('Show console log', lambda i, it: self.toggle_console(),
                             checked=lambda it: console_log.is_shown()),
            pystray.MenuItem('Exit', lambda i, it: self.quit()),
        ]
        return pystray.Menu(*items)

    # ---- actions -------------------------------------------------------

    def toggle_overlay(self):
        self.overlay = not self.overlay
        self._persist_overlay()
        self._write_control()
        self.tray.refresh()

    def toggle_clickthrough(self):
        self.clickthrough = not self.clickthrough
        self._persist_overlay()
        self._write_control()
        self.tray.refresh()

    def toggle_text_bg(self):
        self.text_bg = not self.text_bg
        self._persist_overlay()
        self._write_control()
        self.tray.refresh()

    def toggle_module(self, module):
        self.modules[module] = not self.modules[module]
        logger.info(f"module {module} -> {self.modules[module]}")
        self._persist_modules()
        self._write_control()
        if self.modules[module]:
            self._spawn(module)
        else:
            self._terminate(module)
        self.tray.refresh()

    def toggle_monitor(self):
        self.monitor_clipboard = not self.monitor_clipboard
        self._write_control()
        self.tray.refresh()

    def corp_toggle(self):
        self.corp_count += 1
        self._write_control()

    def show_all(self):
        # Tell the dps window to clear its ignore list (re-show every char).
        self.dps_show_all += 1
        self._write_control()

    def set_opacity(self, pct):
        # Shared opacity for both windows.
        self.opacity_pct = int(pct)
        self._persist_overlay()
        self._write_control()
        self.tray.refresh()
        self.tray.request_reopen()  # keep menu open for quick level changes

    def toggle_console(self):
        console_log.toggle(level=C.get('logging', {}).get('level', 'INFO').upper())
        self.tray.refresh()

    def quit(self):
        logger.info("supervisor quit")
        self._quit = True
        self.modules = {m: False for m in MODULES}
        self._write_control()
        for m in MODULES:
            self._terminate(m)
        self.tray.stop()

    # ---- hotkeys -------------------------------------------------------

    def _register_hotkeys(self):
        dscan = C.get('dscan', {})
        bindings = []
        for key, handler in (
            (dscan.get('hotkey_overlay'), self.toggle_overlay),
            (dscan.get('hotkey_clickthrough'), self.toggle_clickthrough),
            (dscan.get('hotkey_bg'), self.toggle_text_bg),
        ):
            if key:
                bindings.append([key, None, handler, True])
        if bindings:
            register_hotkeys(bindings)
            start_checking_hotkeys()
            logger.info(f"registered {len(bindings)} overlay hotkeys")

    # ---- main loop -----------------------------------------------------

    def run(self):
        self._write_control()
        for m in MODULES:
            if self.modules[m]:
                self._spawn(m)
        self.tray.start()
        self._register_hotkeys()
        try:
            while not self._quit:
                self._supervise()
                time.sleep(0.5)
        finally:
            try:
                stop_checking_hotkeys()
            except Exception:
                pass
            for m in MODULES:
                self._terminate(m)


def main():
    Supervisor().run()


if __name__ == '__main__':
    main()
