import json
import random
def extract_character_data(data):
    extracted_data = []
    for entry in data:
        extracted_entry = {
            'name': entry.get('name'),
            'character_id': entry.get('character_id'), 
            'corporation_id': entry.get('corporation_id'),
            'alliance_id': entry.get('alliance_id'),
            'last_active': entry.get('last_active',None)
        }
        extracted_data.append(extracted_entry)

    with open('extracted_characters.json', 'w', encoding='utf-8') as f:
        json.dump(extracted_data, f, indent=2, ensure_ascii=False)

    print(f"Extracted {len(extracted_data)} characters to extracted_characters.json")

def extract_character_data_small(data):
    extracted_data = []
    data = random.sample(data, 100000)
    for entry in data:
        extracted_entry = {
            'name': entry.get('name'),
            'character_id': entry.get('character_id'), 
            'corporation_id': entry.get('corporation_id'),
            'alliance_id': entry.get('alliance_id'),
            'last_active': entry.get('last_active',None)
        }
        extracted_data.append(extracted_entry)

    with open('extracted_characters_small.json', 'w', encoding='utf-8') as f:
        json.dump(extracted_data, f, indent=2, ensure_ascii=False)

    print(f"Extracted {len(extracted_data)} characters to extracted_characters.json")


        
if __name__ == "__main__":

    with open('test_data/char_data/ek_characters.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    extract_character_data(data)
    extract_character_data_small(data)
