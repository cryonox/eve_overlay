import struct
import orjson
import leb128
import io
from pathlib import Path
from glob import glob

INPUT_DIR = Path('test_data/ek_batches_stats')
OUTPUT_DIR = Path('test_data/ek_stats')
CACHE_DIR = Path('cache')
UINT16_MAX = 65535

def encode_signed_leb128(val):
    return leb128.i.encode(val)

def load_trie_ids():
    ids_path = CACHE_DIR / 'ids.bin'
    with open(ids_path, 'rb') as f:
        data = f.read()

    tid2id = []
    bio = io.BytesIO(data)
    while bio.tell() < len(data):
        id_val, _ = leb128.i.decode_reader(bio)
        tid2id.append(id_val)

    print(f"Loaded {len(tid2id):,} trie entries")
    return tid2id

def load_batches():
    stats = {}
    batch_files = sorted(glob(str(INPUT_DIR / 'batch_*.json')))
    
    for fpath in batch_files:
        print(fpath)
        with open(fpath, 'rb') as f:
            data = orjson.loads(f.read())

        stats.update({
            e['id']: {'kills': e.get('kills', 0), 'losses': e.get('losses', 0)}
            for e in data
            if e.get('type') == 'character_id' and e.get('id')
        })

    return stats

def save_merged_json(stats):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / 'merged_stats.json'
    with open(out_path, 'wb') as f:
        f.write(orjson.dumps(stats, option=orjson.OPT_NON_STR_KEYS))
    sz = out_path.stat().st_size
    print(f"Merged JSON: {out_path} ({sz:,} bytes, {len(stats):,} chars)")
    return sz

def save_leb128_bin(stats, tid2id):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / 'stats.bin'
    found = 0
    with open(out_path, 'wb') as f:
        for char_id in tid2id:
            s = stats.get(char_id)
            if s:
                found += 1
                f.write(encode_signed_leb128(s['kills']))
                f.write(encode_signed_leb128(s['losses']))
            else:
                f.write(encode_signed_leb128(0))
                f.write(encode_signed_leb128(0))
    sz = out_path.stat().st_size
    print(f"LEB128 bin:  {out_path} ({sz:,} bytes, {len(tid2id):,} entries)")
    print(f"  - Found: {found:,} / {len(tid2id):,}")
    return sz

def save_uint16_bin(stats, tid2id):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / 'stats_uint16.bin'
    clipped, found = 0, 0
    with open(out_path, 'wb') as f:
        for char_id in tid2id:
            s = stats.get(char_id)
            if s:
                found += 1
                kills, losses = s['kills'], s['losses']
                k, l = min(kills, UINT16_MAX), min(losses, UINT16_MAX)
                if kills > UINT16_MAX or losses > UINT16_MAX:
                    clipped += 1
            else:
                k, l = 0, 0
            f.write(struct.pack('<HH', k, l))
    sz = out_path.stat().st_size
    print(f"uint16 bin:  {out_path} ({sz:,} bytes, {len(tid2id):,} entries)")
    print(f"  - Found: {found:,} / {len(tid2id):,}")
    if clipped:
        print(f"  - {clipped} entries had kills/losses clipped to {UINT16_MAX}")
    return sz

def main():
    print(f"Loading trie IDs from {CACHE_DIR}...")
    tid2id = load_trie_ids()
    print()

    print(f"Loading batches from {INPUT_DIR}...")
    stats = load_batches()
    print(f"Total characters in stats: {len(stats):,}")
    print()

    json_sz = save_merged_json(stats)
    leb_sz = save_leb128_bin(stats, tid2id)
    u16_sz = save_uint16_bin(stats, tid2id)

    print()
    print("Space comparison:")
    print(f"  JSON:       {json_sz:>12,} bytes")
    print(f"  LEB128:     {leb_sz:>12,} bytes ({100*leb_sz/json_sz:.1f}% of JSON)")
    print(f"  uint16:     {u16_sz:>12,} bytes ({100*u16_sz/json_sz:.1f}% of JSON)")
    print(f"  LEB128 vs uint16: {100*leb_sz/u16_sz:.1f}%")

if __name__ == '__main__':
    main()
