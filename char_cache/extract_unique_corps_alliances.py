import json

def extract_unique_corps_alliances():
    with open('test_data/char_data/extracted_characters.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    unique_corps = set()
    unique_alliances = set()
    
    for entry in data:
        corp_id = entry.get('corporation_id')
        alliance_id = entry.get('alliance_id')
        
        if corp_id:
            unique_corps.add(corp_id)
        if alliance_id:
            unique_alliances.add(alliance_id)
    
    corp_list = sorted(list(unique_corps))
    alliance_list = sorted(list(unique_alliances))
    
    result = {
        'corporations': corp_list,
        'alliances': alliance_list,
        'corp_count': len(corp_list),
        'alliance_count': len(alliance_list)
    }
    
    with open('test_data/char_data/unique_corps_alliances.json', 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"Found {len(corp_list)} unique corporations")
    print(f"Found {len(alliance_list)} unique alliances")
    print("Saved to test_data/char_data/unique_corps_alliances.json")
    
    return result

if __name__ == "__main__":
    extract_unique_corps_alliances()
