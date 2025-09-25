import json
import marisa_trie
import sys
import leb128
import vu128

def build_character_trie(data):
    keys_values = []
    
    for entry in data:
        name = entry.get('name')
        if not name:
            continue
            
        char_id = entry.get('character_id') or 0
        corp_id = entry.get('corporation_id') or 0
        
        encoded_val = bytes(leb128.i.encode(char_id) + leb128.i.encode(corp_id))
        keys_values.append((name, encoded_val))
    
    trie = marisa_trie.BytesTrie(keys_values)
    trie.save('../test_data/char_data/characters.bin')
    
    print(f"Built trie with {len(keys_values)} characters")
    return trie

def build_character_trie_separate(data):
    names = []
    char_corp_data = []
    
    for entry in data:
        name = entry.get('name')
        if not name:
            continue
            
        char_id = entry.get('character_id') or 0
        corp_id = entry.get('corporation_id') or 0
        
        names.append(name)
        char_corp_data.append((char_id, corp_id))
    
    trie = marisa_trie.Trie(names)
    trie.save('../test_data/char_data/characters_names.trie')
    
    # Create binary data ordered by trie_id
    ordered_data = [None] * len(trie)
    for i, (char_id, corp_id) in enumerate(char_corp_data):
        name = names[i]
        trie_id = trie[name]
        ordered_data[trie_id] = (char_id, corp_id)
    
    # Write binary file with sequential char_id, corp_id pairs
    with open('../test_data/char_data/characters_data.bin', 'wb') as f:
        for char_id, corp_id in ordered_data:
            encoded_data = leb128.i.encode(char_id) + leb128.i.encode(corp_id)
            f.write(encoded_data)
    
    print(f"Built separate trie with {len(names)} characters")
    print(f"Names saved to characters_names.trie")
    print(f"Data saved to characters_data.bin")
    return trie

def build_character_trie_vu128(data):
    names = []
    char_corp_data = []
    
    for entry in data:
        name = entry.get('name')
        if not name:
            continue
            
        char_id = entry.get('character_id') or 0
        corp_id = entry.get('corporation_id') or 0
        
        names.append(name)
        char_corp_data.append((char_id, corp_id))
    
    trie = marisa_trie.Trie(names)
    trie.save('../test_data/char_data/characters_names_vu128.trie')
    
    # Create binary data ordered by trie_id
    ordered_data = [None] * len(trie)
    for i, (char_id, corp_id) in enumerate(char_corp_data):
        name = names[i]
        trie_id = trie[name]
        ordered_data[trie_id] = (char_id, corp_id)
    
    # Write binary file with sequential char_id, corp_id pairs using vu128
    with open('../test_data/char_data/characters_data_vu128.bin', 'wb') as f:
        for char_id, corp_id in ordered_data:
            encoded_data = vu128.encode(char_id) + vu128.encode(corp_id)
            f.write(encoded_data)
    
    print(f"Built vu128 trie with {len(names)} characters")
    print(f"Names saved to characters_names_vu128.trie")
    print(f"Data saved to characters_data_vu128.bin")
    return trie

def extract_active_characters(data, cutoff_date="2007-07"):
    active_chars = []
    for entry in data:
        last_active = entry.get('last_active')
        if last_active and last_active >= cutoff_date:
            active_chars.append(entry)
    
    with open('../test_data/char_data/extracted_characters_active.json', 'w', encoding='utf-8') as f:
        json.dump(active_chars, f, indent=2, ensure_ascii=False)
    
    print(f"Extracted {len(active_chars)} active characters to extracted_characters_active.json")
    return active_chars

if __name__ == "__main__":
    with open('../test_data/char_data/extracted_characters_active.json', 'r', encoding='utf-8') as f:
        extracted_data = json.load(f)
    
    #build_character_trie(extracted_data)
    build_character_trie_separate(extracted_data)
    #build_character_trie_vu128(extracted_data)
    #extract_active_characters(extracted_data)
