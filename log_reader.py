import os
import time
import platform
import re
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from loguru import logger
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from config import C
# this holds the regex strings for all the different languages the eve game log can be in
_logLanguageRegex = {
    'english': {
        'character': "(?<=Listener: ).*",
        'sessionTime': "(?<=Session Started: ).*",
        'pilotAndWeapon': '(?:.*ffffffff>(?P<default_pilot>[^\(\)<>]*)(?:\[.*\((?P<default_ship>.*)\)<|<)/b.*> \-(?: (?P<default_weapon>.*?)(?: \-|<)|.*))',
        'damageOut': "\(combat\) <.*?><b>([0-9]+).*>to<",
        'damageIn': "\(combat\) <.*?><b>([0-9]+).*>from<",
        'armorRepairedOut': "\(combat\) <.*?><b>([0-9]+).*> remote armor repaired to <",
        'hullRepairedOut': "\(combat\) <.*?><b>([0-9]+).*> remote hull repaired to <",
        'shieldBoostedOut': "\(combat\) <.*?><b>([0-9]+).*> remote shield boosted to <",
        'armorRepairedIn': "\(combat\) <.*?><b>([0-9]+).*> remote armor repaired by <",
        'hullRepairedIn': "\(combat\) <.*?><b>([0-9]+).*> remote hull repaired by <",
        'shieldBoostedIn': "\(combat\) <.*?><b>([0-9]+).*> remote shield boosted by <",
        'capTransferedOut': "\(combat\) <.*?><b>([0-9]+).*> remote capacitor transmitted to <",
        'capNeutralizedOut': "\(combat\) <.*?ff7fffff><b>([0-9]+).*> energy neutralized <",
        'nosRecieved': "\(combat\) <.*?><b>\+([0-9]+).*> energy drained from <",
        'capTransferedIn': "\(combat\) <.*?><b>([0-9]+).*> remote capacitor transmitted by <",
        'capNeutralizedIn': "\(combat\) <.*?ffe57f7f><b>([0-9]+).*> energy neutralized <",
        'nosTaken': "\(combat\) <.*?><b>\-([0-9]+).*> energy drained to <",
        'mined': "\(mining\) .*? <.*?><.*?>([0-9]+).*> units of <.*?><.*?>([^<\n]+)"
    },
    'russian': {
        'character': "(?<=Слушатель: ).*",
        'sessionTime': "(?<=Сеанс начат: ).*",
        'pilotAndWeapon': '(?:.*ffffffff>(?:<localized .*?>)?(?P<default_pilot>[^\(\)<>]*)(?:\[.*\((?:<localized .*?>)?(?P<default_ship>.*)\)<|<)/b.*> \-(?: (?:<localized .*?>)?(?P<default_weapon>.*?)(?: \-|<)|.*))',
        'damageOut': "\(combat\) <.*?><b>([0-9]+).*>на<",
        'damageIn': "\(combat\) <.*?><b>([0-9]+).*>из<",
        'armorRepairedOut': "\(combat\) <.*?><b>([0-9]+).*> единиц запаса прочности брони отремонтировано <",
        'hullRepairedOut': "\(combat\) <.*?><b>([0-9]+).*> единиц запаса прочности корпуса отремонтировано <",
        'shieldBoostedOut': "\(combat\) <.*?><b>([0-9]+).*> единиц запаса прочности щитов накачано <",
        'armorRepairedIn': "\(combat\) <.*?><b>([0-9]+).*> единиц запаса прочности брони получено дистанционным ремонтом от <",
        'hullRepairedIn': "\(combat\) <.*?><b>([0-9]+).*> единиц запаса прочности корпуса получено дистанционным ремонтом от <",
        'shieldBoostedIn': "\(combat\) <.*?><b>([0-9]+).*> единиц запаса прочности щитов получено накачкой от <",
        'capTransferedOut': "\(combat\) <.*?><b>([0-9]+).*> единиц запаса энергии накопителя отправлено в <",
        'capNeutralizedOut': "\(combat\) <.*?ff7fffff><b>([0-9]+).*> энергии нейтрализовано <",
        'nosRecieved': "\(combat\) <.*?><b>\+([0-9]+).*> энергии извлечено из <",
        'capTransferedIn': "\(combat\) <.*?><b>([0-9]+).*> единиц запаса энергии накопителя получено от <",
        'capNeutralizedIn': "\(combat\) <.*?ffe57f7f><b>([0-9]+).*> энергии нейтрализовано <",
        'nosTaken': "\(combat\) <.*?><b>\-([0-9]+).*> энергии извлечено и передано <",
        'mined': "\(mining\) .*? <.*?><.*?>([0-9]+).*(?:<localized .*?>)?(.+)\*<"
    },
    'french': {
        'character': "(?<=Auditeur: ).*",
        'sessionTime': "(?<=Session commencée: ).*",
        'pilotAndWeapon': '(?:.*ffffffff>(?:<localized .*?>)?(?P<default_pilot>[^\(\)<>]*)(?:\[.*\((?:<localized .*?>)?(?P<default_ship>.*)\)<|<)/b.*> \-(?: (?:<localized .*?>)?(?P<default_weapon>.*?)(?: \-|<)|.*))',
        'damageOut': "\(combat\) <.*?><b>([0-9]+).*>à<",
        'damageIn': "\(combat\) <.*?><b>([0-9]+).*>de<",
        'armorRepairedOut': "\(combat\) <.*?><b>([0-9]+).*> points de blindage transférés à distance à <",
        'hullRepairedOut': "\(combat\) <.*?><b>([0-9]+).*> points de structure transférés à distance à <",
        'shieldBoostedOut': "\(combat\) <.*?><b>([0-9]+).*> points de boucliers transférés à distance à <",
        'armorRepairedIn': "\(combat\) <.*?><b>([0-9]+).*> points de blindage réparés à distance par <",
        'hullRepairedIn': "\(combat\) <.*?><b>([0-9]+).*> points de structure réparés à distance par <",
        'shieldBoostedIn': "\(combat\) <.*?><b>([0-9]+).*> points de boucliers transférés à distance par <",
        'capTransferedOut': "\(combat\) <.*?><b>([0-9]+).*> points de capaciteur transférés à distance à <",
        'capNeutralizedOut': "\(combat\) <.*?ff7fffff><b>([0-9]+).*> d'énergie neutralisée en faveur de <",
        'nosRecieved': "\(combat\) <.*?><b>([0-9]+).*> d'énergie siphonnée aux dépens de <",
        'capTransferedIn': "\(combat\) <.*?><b>([0-9]+).*> points de capaciteur transférés à distance par <",
        'capNeutralizedIn': "\(combat\) <.*?ffe57f7f><b>([0-9]+).*> d'énergie neutralisée aux dépens de <",
        'nosTaken': "\(combat\) <.*?><b>([0-9]+).*> d'énergie siphonnée en faveur de <",
        'mined': "\(mining\) .*? <.*?><.*?>([0-9]+).*(?:<localized .*?>)?(.+)\*<"
    },
    'german': {
        'character': "(?<=Empfänger: ).*",
        'sessionTime': "(?<=Sitzung gestartet: ).*",
        'pilotAndWeapon': '(?:.*ffffffff>(?:<localized .*?>)?(?P<default_pilot>[^\(\)<>]*)(?:\[.*\((?:<localized .*?>)?(?P<default_ship>.*)\)<|<)/b.*> \-(?: (?:<localized .*?>)?(?P<default_weapon>.*?)(?: \-|<)|.*))',
        'damageOut': "\(combat\) <.*?><b>([0-9]+).*>nach<",
        'damageIn': "\(combat\) <.*?><b>([0-9]+).*>von<",
        'armorRepairedOut': "\(combat\) <.*?><b>([0-9]+).*> Panzerungs-Fernreparatur zu <",
        'hullRepairedOut': "\(combat\) <.*?><b>([0-9]+).*> Rumpf-Fernreparatur zu <",
        'shieldBoostedOut': "\(combat\) <.*?><b>([0-9]+).*> Schildfernbooster aktiviert zu <",
        'armorRepairedIn': "\(combat\) <.*?><b>([0-9]+).*> Panzerungs-Fernreparatur von <",
        'hullRepairedIn': "\(combat\) <.*?><b>([0-9]+).*> Rumpf-Fernreparatur von <",
        'shieldBoostedIn': "\(combat\) <.*?><b>([0-9]+).*> Schildfernbooster aktiviert von <",
        'capTransferedOut': "\(combat\) <.*?><b>([0-9]+).*> Fernenergiespeicher übertragen zu <",
        'capNeutralizedOut': "\(combat\) <.*?ff7fffff><b>([0-9]+).*> Energie neutralisiert <",
        'nosRecieved': "\(combat\) <.*?><b>\+([0-9]+).*> Energie transferiert von <",
        'capTransferedIn': "\(combat\) <.*?><b>([0-9]+).*> Fernenergiespeicher übertragen von <",
        'capNeutralizedIn': "\(combat\) <.*?ffe57f7f><b>\-([0-9]+).*> Energie neutralisiert <",
        'nosTaken': "\(combat\) <.*?><b>\-([0-9]+).*> Energie transferiert zu <",
        'mined': "\(mining\) .*? <.*?><.*?>([0-9]+).*(?:<localized .*?>)?(.+)\*<"
    },
    'japanese': {
        'character': "(?<=傍聴者: ).*",
        'sessionTime': "(?<=セッション開始: ).*",
        'pilotAndWeapon': '(?:.*ffffffff>(?:<localized .*?>)?(?P<default_pilot>[^\(\)<>]*)(?:\[.*\((?:<localized .*?>)?(?P<default_ship>.*)\)<|<)/b.*> \-(?: (?:<localized .*?>)?(?P<default_weapon>.*?)(?: \-|<)|.*))',
        'damageOut': "\(combat\) <.*?><b>([0-9]+).*>対象:<",
        'damageIn': "\(combat\) <.*?><b>([0-9]+).*>攻撃者:<",
        'armorRepairedOut': "\(combat\) <.*?><b>([0-9]+).*> remote armor repaired to <",
        'hullRepairedOut': "\(combat\) <.*?><b>([0-9]+).*> remote hull repaired to <",
        'shieldBoostedOut': "\(combat\) <.*?><b>([0-9]+).*> remote shield boosted to <",
        'armorRepairedIn': "\(combat\) <.*?><b>([0-9]+).*> remote armor repaired by <",
        'hullRepairedIn': "\(combat\) <.*?><b>([0-9]+).*> remote hull repaired by <",
        'shieldBoostedIn': "\(combat\) <.*?><b>([0-9]+).*> remote shield boosted by <",
        'capTransferedOut': "\(combat\) <.*?><b>([0-9]+).*> remote capacitor transmitted to <",
        'capNeutralizedOut': "\(combat\) <.*?ff7fffff><b>([0-9]+).*> エネルギーニュートラライズ 対象:<",
        'nosRecieved': "\(combat\) <.*?><b>\+([0-9]+).*> エネルギードレイン 対象:<",
        'capTransferedIn': "\(combat\) <.*?><b>([0-9]+).*> remote capacitor transmitted by <",
        'capNeutralizedIn': "\(combat\) <.*?ffe57f7f><b>([0-9]+).*>のエネルギーが解放されました<",
        'nosTaken': "\(combat\) <.*?><b>\-([0-9]+).*> エネルギードレイン 攻撃者:<",
        'mined': "\(mining\) .*? <.*?><.*?>([0-9]+).*(?:<localized .*?>)?(.+)\*<"
    },
    'chinese':{
        'character': "(?<=收听者: ).*",
        'sessionTime': "(?<=进程开始: ).*",
        'pilotAndWeapon': '(?:.*ffffffff>(?:<localized .*?>)?(?P<default_pilot>[^\(\)<>]*)(?:\[.*\((?:<localized .*?>)?(?P<default_ship>.*)\)<|<)/b.*> \-(?: (?:<localized .*?>)?(?P<default_weapon>.*?)(?: \-|<)|.*))',
        'damageOut': "\(combat\) <.*?><b>([0-9]+).*>对<",
        'damageIn': "\(combat\) <.*?><b>([0-9]+).*>来自<",
        'armorRepairedOut': "\(combat\) <.*?><b>([0-9]+).*>远程装甲维修量至<",
        'hullRepairedOut': "\(combat\) <.*?><b>([0-9]+).*>远程结构维修量至<",
        'shieldBoostedOut': "\(combat\) <.*?><b>([0-9]+).*>远程护盾回充增量至<",
        'armorRepairedIn': "\(combat\) <.*?><b>([0-9]+).*>远程装甲维修量由<",
        'hullRepairedIn': "\(combat\) <.*?><b>([0-9]+).*>远程结构维修量由<",
        'shieldBoostedIn': "\(combat\) <.*?><b>([0-9]+).*>远程护盾回充增量由<",
        'capTransferedOut': "\(combat\) <.*?><b>([0-9]+).*>远程电容传输至<",
        'capNeutralizedOut': "\(combat\) <.*?ff7fffff><b>([0-9]+).*>能量中和<",
        'nosRecieved': "\(combat\) <.*?><b>\+([0-9]+).*>被从<",
        'capTransferedIn': "\(combat\) <.*?><b>([0-9]+).*>远程电容传输量由<",
        'capNeutralizedIn': "\(combat\) <.*?ffe57f7f><b>([0-9]+).*>能量中和<",
        'nosTaken': "\(combat\) <.*?><b>\-([0-9]+).*>被吸取到<",
        'mined': "\(mining\) .*? <.*?><.*?>([0-9]+).*(?:<localized .*?>)?(.+)\*<"
        }
}


def find_eve_logs_dir():
    if platform.system() == "Windows":
        try:
            import win32com.client
            oShell = win32com.client.Dispatch("Wscript.Shell")
            return Path(oShell.SpecialFolders("MyDocuments")) / "EVE" / "logs" / "Gamelogs"
        except:
            user_profile = os.environ.get('USERPROFILE')
            return Path(user_profile) / 'Documents' / 'EVE' / 'logs' / 'Gamelogs'
    else:
        return Path(os.environ['HOME']) / "Documents" / "EVE" / "logs" / "Gamelogs"


def scan_log_directory(logs_dir, target_chars=None):
    """Single pass over Gamelogs. Returns dict[char_name] = (Path, language).
    Stops early once every name in target_chars has been resolved.
    """
    result: dict[str, tuple] = {}
    if not logs_dir.exists():
        return result

    all_logs = list(logs_dir.glob("*.txt"))
    all_logs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    target_set = set(target_chars) if target_chars else None
    char_regexes = [(lang, re.compile(r['character'])) for lang, r in _logLanguageRegex.items()]

    for log_file in all_logs:
        if target_set is not None and target_set.issubset(result.keys()):
            break
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                first_lines = [f.readline() for _ in range(10)]
        except Exception:
            continue

        for line in first_lines:
            matched = False
            for lang, rx in char_regexes:
                m = rx.search(line)
                if m:
                    name = m.group(0)
                    if name not in result:
                        result[name] = (log_file, lang)
                    matched = True
                    break
            if matched:
                break

    return result


class LogFileHandler(FileSystemEventHandler):
    def __init__(self, log_reader):
        super().__init__()
        self.log_reader = log_reader

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not path.suffix == '.txt':
            return
        self.log_reader._on_new_file_created(path)


class LogReader:
    def __init__(self, char_name, initial_log_file=None, initial_language=None):
        self.char_name = char_name
        self.logs_dir = find_eve_logs_dir()
        self.log_file = None
        self.log_char_id = None
        self.language = None
        self.damage_out_events = []
        self.damage_in_events = []
        self.last_mined_ts = None
        self.last_read_position = 0
        self.pending_new_file = None
        self.observer = None
        if initial_log_file is not None and initial_language is not None:
            self._initialize_from(initial_log_file, initial_language)
        else:
            self._initialize()
        self._start_watcher()
        logger.debug(f"LogReader initialized for {char_name}, watching {self.logs_dir}")

    def _initialize_from(self, log_file, language):
        self.log_file = log_file
        self.log_char_id = self._extract_char_id(log_file)
        self.language = language
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                f.seek(0, 2)
                self.last_read_position = f.tell()
        except Exception as e:
            logger.error(f"Error setting initial file position: {e}")
            self.last_read_position = 0

        
    def _extract_char_id(self, log_path):
        parts = log_path.stem.split('_')
        return parts[2] if len(parts) >= 3 else None

    def _initialize(self):
        log_file = self._get_latest_log_file()
        if not log_file:
            return

        self.log_file = log_file
        self.log_char_id = self._extract_char_id(log_file)
        logger.info(f"[{self.char_name}] Processing log: {log_file.name}")
        self._detect_language()

        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                f.seek(0, 2)
                self.last_read_position = f.tell()
        except Exception as e:
            logger.error(f"Error setting initial file position: {e}")
            self.last_read_position = 0
    
    def _detect_language(self):
        if not self.log_file:
            return
            
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                first_lines = [f.readline() for _ in range(10)]
                for line in first_lines:
                    for lang, regex in _logLanguageRegex.items():
                        character = re.search(regex['character'], line)
                        if character and character.group(0) == self.char_name:
                            self.language = lang
                            return
        except Exception as e:
            logger.error(f"Error detecting language: {e}")
            
    
    def _get_latest_log_file(self):
        all_logs = list(self.logs_dir.glob("*.txt"))
        if not all_logs:
            return None
            
        for log_file in sorted(all_logs, key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    first_lines = [f.readline() for _ in range(10)]
                    for line in first_lines:
                        for lang, regex in _logLanguageRegex.items():
                            character = re.search(regex['character'], line)
                            if character and character.group(0) == self.char_name:
                                return log_file
            except:
                continue
        
        return None

    def _start_watcher(self):
        if not self.logs_dir.exists():
            return
        self.observer = Observer()
        handler = LogFileHandler(self)
        self.observer.schedule(handler, str(self.logs_dir), recursive=False)
        self.observer.start()

    def _stop_watcher(self):
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=1)
            self.observer = None

    def _on_new_file_created(self, path):
        if not self.log_char_id:
            return
        file_char_id = self._extract_char_id(path)
        if file_char_id != self.log_char_id:
            return
        self.pending_new_file = path

    def _switch_to_pending_file(self):
        if not self.pending_new_file:
            return False
        path = self.pending_new_file
        self.pending_new_file = None

        if path == self.log_file:
            return False

        try:
            with open(path, 'r', encoding='utf-8') as f:
                first_lines = [f.readline() for _ in range(10)]
                for line in first_lines:
                    for regex in _logLanguageRegex.values():
                        char = re.search(regex['character'], line)
                        if char and char.group(0) == self.char_name:
                            logger.info(f"Switching to newer log: {path.name}")
                            self.log_file = path
                            self.last_read_position = 0
                            self._detect_language()
                            return True
        except Exception:
            pass
        return False

    def stop(self):
        self._stop_watcher()

    def __del__(self):
        self._stop_watcher()

    def update(self):
        if not self.log_file or not self.language:
            self._initialize()
            if not self.log_file or not self.language:
                return False

        self._switch_to_pending_file()

        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                f.seek(self.last_read_position)
                new_content = f.read()
                self.last_read_position = f.tell()

                if not new_content:
                    return False

                self._process_log_content(new_content)
                return True
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
            return False
    
    def _process_log_content(self, content):
        now = time.time()
        
        # Process damage out
        damage_out_regex = re.compile(_logLanguageRegex[self.language]['damageOut'])
        for match in damage_out_regex.finditer(content):
            amount = int(match.group(1) or 0)
            if amount > 0:
                self.damage_out_events.append((now, amount))
        
        # Process damage in
        damage_in_regex = re.compile(_logLanguageRegex[self.language]['damageIn'])
        for match in damage_in_regex.finditer(content):
            amount = int(match.group(1) or 0)
            if amount > 0:
                self.damage_in_events.append((now, amount))

        # Process mining — track last-event timestamp for stall detection
        mined_regex = re.compile(_logLanguageRegex[self.language]['mined'])
        for match in mined_regex.finditer(content):
            amount = int(match.group(1) or 0)
            if amount > 0:
                self.last_mined_ts = now

        # Clean up old events (older than 60 seconds)
        self._cleanup_old_events()
    
    def _cleanup_old_events(self):
        now = time.time()
        win = C.dps.get('dps_window', 30)
        self.damage_out_events = [(ts, dmg) for ts, dmg in self.damage_out_events
                                 if now - ts <= win]
        self.damage_in_events = [(ts, dmg) for ts, dmg in self.damage_in_events
                                if now - ts <= win]

    def get_dps_out(self):
        return self._calculate_dps(self.damage_out_events)

    def get_dps_in(self):
        return self._calculate_dps(self.damage_in_events)

    def get_mining_idle_sec(self):
        if self.last_mined_ts is None:
            return None
        return time.time() - self.last_mined_ts

    def get_total_damage_out(self):
        return sum(dmg for _, dmg in self.damage_out_events)

    def get_total_damage_in(self):
        return sum(dmg for _, dmg in self.damage_in_events)

    def _calculate_dps(self, damage_events):
        if not damage_events:
            return 0

        now = time.time()
        win = C.dps.get('dps_window', 30)
        recent_events = [(ts, dmg) for ts, dmg in damage_events if now - ts <= win]

        if not recent_events:
            return 0

        total_damage = sum(dmg for _, dmg in recent_events)
        first_event_time = min(ts for ts, _ in recent_events)
        time_span = now - first_event_time

        min_span = min(1, win * 0.04)
        if time_span < min_span:
            return 0

        return total_damage / max(time_span, win)
