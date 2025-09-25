import json
import marisa_trie
import leb128
from pathlib import Path
import utils
from tqdm import tqdm

class CacheManager:
    def __init__(self, cache_dir='test_data/char_data'):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._trie = None
        self._tid2id = None
        self._name2tid = None
        self._tid2name = None
        self._char_info = None
        self._corp_id_to_name = None
        self._alliance_id_to_name = None
        self._cache_loaded = False
        
    def _load_cache(self):
        if self._cache_loaded:
            return
        
        print("Loading cache...")
        trie_path = self.cache_dir / 'names.trie'
        ids_path = self.cache_dir / 'ids.bin'
        char_info_path = self.cache_dir / 'char_info.bin'
        corp_mappings_path = self.cache_dir / 'corp_mappings.json'
        alliance_mappings_path = self.cache_dir / 'alliance_mappings.json'
        
        # Load mappings
        if corp_mappings_path.exists():
            with open(corp_mappings_path, 'r') as f:
                self._corp_id_to_name = {int(k): v for k, v in json.load(f).items()}
        
        if alliance_mappings_path.exists():
            with open(alliance_mappings_path, 'r') as f:
                self._alliance_id_to_name = {int(k): v for k, v in json.load(f).items()}
        
        if self._trie is None and trie_path.exists():
            print("  Loading trie...")
            self._trie = marisa_trie.Trie()
            self._trie.load(str(trie_path))
            print(f"  Trie loaded: {len(self._trie):,} entries")
        
        if self._tid2id is None and ids_path.exists():
            print("  Loading IDs...")
            self._tid2id = []
            with open(ids_path, 'rb') as f:
                with tqdm(desc="Loading IDs", unit="entries") as pbar:
                    while True:
                        try:
                            id_val, _ = leb128.i.decode_reader(f)
                            self._tid2id.append(id_val)
                            pbar.update(1)
                        except:
                            break
            print(f"  IDs loaded: {len(self._tid2id):,} total")
        
        if self._char_info is None and char_info_path.exists():
            print("  Loading char info...")
            self._char_info = [None] * len(self._trie) if self._trie else []
            with open(char_info_path, 'rb') as f:
                with tqdm(desc="Loading char info", unit="entries") as pbar:
                    idx = 0
                    while True:
                        try:
                            corp_id, _ = leb128.i.decode_reader(f)
                            alliance_id, _ = leb128.i.decode_reader(f)
                            if corp_id == 0:
                                self._char_info[idx] = None
                            else:
                                self._char_info[idx] = (corp_id, alliance_id)
                            idx += 1
                            pbar.update(1)
                        except:
                            break
            print(f"  Char info loaded: {len(self._char_info):,} total")
        
        if self._name2tid is None and self._trie:
            print("  Building name mappings...")
            self._name2tid = {}
            self._tid2name = {}
            for tid in tqdm(range(len(self._trie)), desc="Building mappings"):
                name = self._trie.restore_key(tid)
                self._name2tid[name] = tid
                self._tid2name[tid] = name
            print(f"  Name mappings built: {len(self._name2tid):,} total")
        
        self._cache_loaded = True
        print("Cache loading complete")
    
    def get_tid(self, name):
        return self._name2tid.get(name)

    def get_id_by_tid(self, trie_id):
        if self._tid2id and 0 <= trie_id < len(self._tid2id):
            return self._tid2id[trie_id]
        return None
    
    def get_names_by_tids_batch(self, trie_ids):
        if not self._tid2name:
            return {}
        return {tid: self._tid2name[tid] for tid in trie_ids if tid in self._tid2name}
    
    def get_ids_by_tids_batch(self, trie_ids):
        if not self._tid2id:
            return {}
        return {tid: self._tid2id[tid] 
               for tid in trie_ids 
               if 0 <= tid < len(self._tid2id)}
    
    def get_tids_batch(self, names):
        if not self._name2tid:
            return {}
        return {name: self._name2tid[name] for name in names if name in self._name2tid}
    

    def build_cache(self, chars_file='test_data/char_data/extracted_characters_active.json', 
                           corps_alliances_file='test_data/char_data/corps_alliances_with_names.json'):
        
        print("Loading character data...")
        with open(chars_file, 'r', encoding='utf-8') as f:
            char_data = json.load(f)
        
        print("Loading corp/alliance data...")
        with open(corps_alliances_file, 'r', encoding='utf-8') as f:
            corp_ally_data = json.load(f)
        
        names = []
        ids_data = []
        char_info_data = []
        corp_id_to_name = {}
        alliance_id_to_name = {}
        
        print(f"Processing {len(char_data)} characters...")
        for entry in tqdm(char_data, desc="Processing characters"):
            char_name = entry.get('name')
            char_id = entry.get('character_id')
            if char_name and char_id:
                names.append(char_name)
                ids_data.append(char_id)
                corp_id = entry.get('corporation_id') or 0
                alliance_id = entry.get('alliance_id') or 0
                char_info_data.append((corp_id, alliance_id))
        
        print(f"Processing {len(corp_ally_data['corporations'])} corporations...")
        for corp_id, corp_name in tqdm(corp_ally_data['corporations'].items(), desc="Processing corporations"):
            if corp_name and corp_name != 'Unknown':
                corp_id_to_name[int(corp_id)] = corp_name
                names.append(f"#{corp_name}")
                ids_data.append(int(corp_id))
                char_info_data.append((0, 0))
        
        print(f"Processing {len(corp_ally_data['alliances'])} alliances...")
        for alliance_id, alliance_name in tqdm(corp_ally_data['alliances'].items(), desc="Processing alliances"):
            if alliance_name and alliance_name != 'Unknown':
                alliance_id_to_name[int(alliance_id)] = alliance_name
                names.append(f"@{alliance_name}")
                ids_data.append(int(alliance_id))
                char_info_data.append((0, 0))
        
        # Store mappings
        self._corp_id_to_name = corp_id_to_name
        self._alliance_id_to_name = alliance_id_to_name
        
        # Save mappings to files
        with open(self.cache_dir / 'corp_mappings.json', 'w') as f:
            json.dump(corp_id_to_name, f)
        with open(self.cache_dir / 'alliance_mappings.json', 'w') as f:
            json.dump(alliance_id_to_name, f)
        
        print("Building trie...")
        trie = marisa_trie.Trie(names)
        
        print("Creating binary data...")
        ordered_ids = [None] * len(trie)
        ordered_char_info = [None] * len(trie)
        for i, (id_val, char_info) in enumerate(tqdm(zip(ids_data, char_info_data), desc="Ordering data", total=len(ids_data))):
            name = names[i]
            trie_id = trie[name]
            ordered_ids[trie_id] = id_val
            ordered_char_info[trie_id] = char_info
        
        print("Writing files...")
        trie_path = self.cache_dir / 'names.trie'
        ids_path = self.cache_dir / 'ids.bin'
        char_info_path = self.cache_dir / 'char_info.bin'
        
        trie.save(str(trie_path))
        
        with open(ids_path, 'wb') as f:
            for id_val in tqdm(ordered_ids, desc="Writing IDs"):
                f.write(leb128.i.encode(id_val))
        
        with open(char_info_path, 'wb') as f:
            for char_info in tqdm(ordered_char_info, desc="Writing char info"):
                corp_id, alliance_id = char_info
                f.write(leb128.i.encode(corp_id))
                f.write(leb128.i.encode(alliance_id))
        
        print(f"Built cache with {len(names)} entries")
        print(f"Cache saved to {trie_path}, {ids_path}, and {char_info_path}")
        
        return trie

    
    def test_cache(self, chars_file='test_data/char_data/extracted_characters_active.json',
                          corps_alliances_file='corps_alliances_with_names.json'):
        print("Testing cache...")
        
        with open(chars_file, 'r', encoding='utf-8') as f:
            char_data = json.load(f)
        
        with open(corps_alliances_file, 'r', encoding='utf-8') as f:
            corp_ally_data = json.load(f)
        
        
        if not self._trie or not self._tid2id:
            print("Cache not loaded properly")
            return False
        
        errors = 0
        total_tested = 0
        
        for entry in char_data[:1000]:
            char_name = entry.get('name')
            char_id = entry.get('character_id')
            if char_name and char_id:
                tid = self.get_tid(char_name)
                if tid is None:
                    print(f"Char name not found: {char_name}")
                    errors += 1
                else:
                    cached_id = self.get_id_by_tid(tid)
                    if cached_id != char_id:
                        print(f"Char ID mismatch: {char_name} -> expected {char_id}, got {cached_id}")
                        errors += 1
                total_tested += 1
        
        for corp_id, corp_name in list(corp_ally_data['corporations'].items())[:1000]:
            if corp_name and corp_name != 'Unknown':
                prefixed_name = f"#{corp_name}"
                tid = self.get_tid(prefixed_name)
                if tid is None:
                    print(f"Corp name not found: {prefixed_name}")
                    errors += 1
                else:
                    cached_id = self.get_id_by_tid(tid)
                    if cached_id != int(corp_id):
                        print(f"Corp ID mismatch: {prefixed_name} -> expected {corp_id}, got {cached_id}")
                        errors += 1
                total_tested += 1
        
        for alliance_id, alliance_name in list(corp_ally_data['alliances'].items())[:1000]:
            if alliance_name and alliance_name != 'Unknown':
                prefixed_name = f"@{alliance_name}"
                tid = self.get_tid(prefixed_name)
                if tid is None:
                    print(f"Alliance name not found: {prefixed_name}")
                    errors += 1
                else:
                    cached_id = self.get_id_by_tid(tid)
                    if cached_id != int(alliance_id):
                        print(f"Alliance ID mismatch: {prefixed_name} -> expected {alliance_id}, got {cached_id}")
                        errors += 1
                total_tested += 1
        
        print(f"Tested {total_tested} entries, {errors} errors")
        return errors == 0

    def get_char_info(self, char_name):
        utils.tick('cache_load')
        self._load_cache()
        utils.tock('cache_load')
        
        tid = self.get_tid(char_name)
        if tid is None:
            return None
        
        char_id = self.get_id_by_tid(tid)
        if char_id is None:
            return None
        
        if not self._char_info or tid >= len(self._char_info) or self._char_info[tid] is None:
            return None
        
        corp_id, alliance_id = self._char_info[tid]
        
        corp_name = self._corp_id_to_name.get(corp_id, 'Unknown') if corp_id else 'Unknown'
        alliance_name = self._alliance_id_to_name.get(alliance_id) if alliance_id else None
        
        return {
            'char_id': char_id,
            'corp_id': corp_id,
            'alliance_id': alliance_id,
            'corp_name': corp_name,
            'alliance_name': alliance_name
        }

if __name__ == "__main__":
    import time
    
    cache = CacheManager()
    cache.build_cache()
    
    #print("\n" + "="*50)
    #cache.test_cache()
    #cache = CacheManager()
    info = cache.get_char_info("cryonox")
    if info:
        print(f"Char ID: {info['char_id']}")
        print(f"Corp: {info['corp_name']} ({info['corp_id']})")
        print(f"Alliance: {info['alliance_name']} ({info['alliance_id']})")

    info = cache.get_char_info("cryonox dps1")
    if info:
        print(f"Char ID: {info['char_id']}")
        print(f"Corp: {info['corp_name']} ({info['corp_id']})")
        print(f"Alliance: {info['alliance_name']} ({info['alliance_id']})")

    info = cache.get_char_info("cryonox bubbly")
    if info:
        print(f"Char ID: {info['char_id']}")
        print(f"Corp: {info['corp_name']} ({info['corp_id']})")
        print(f"Alliance: {info['alliance_name']} ({info['alliance_id']})")
