import marisa_trie
import leb128
import io
import sys
sys.path.append('../')
import utils

def test_jita_against_trie():
    with open('../test_data/jita.txt', 'r', encoding='utf-8') as f:
        jita_names = [line.strip() for line in f if line.strip()]
    
    trie = marisa_trie.BytesTrie()
    trie.load('../test_data/char_data/characters.bin')
    
    found_count = 0
    not_found = []
    
    print(f"Testing {len(jita_names)} jita characters against trie...")
    print(f"Trie contains {len(trie)} characters")
    print()
    
    for name in jita_names:
        if name in trie:
            found_count += 1
            stored_vals = trie[name]
            if stored_vals:
                stored_val = stored_vals[0]
                bio = io.BytesIO(stored_val)
                char_id, pos = leb128.i.decode_reader(bio)
                bio.seek(pos)
                corp_id, _ = leb128.i.decode_reader(bio)
                print(f"✓ {name} -> char_id={char_id}, corp_id={corp_id}")
        else:
            not_found.append(name)
    
    hit_rate = found_count / len(jita_names) * 100
    print(f"\nResults:")
    print(f"Found: {found_count}/{len(jita_names)} ({hit_rate:.1f}%)")
    print(f"Not found: {len(not_found)}")
    
    if not_found:
        print(f"\nMissing characters:")
        for name in not_found[:10]:
            print(f"  - {name}")
        if len(not_found) > 10:
            print(f"  ... and {len(not_found) - 10} more")

if __name__ == "__main__":
    utils.tick()
    test_jita_against_trie()
    utils.tock('check')
