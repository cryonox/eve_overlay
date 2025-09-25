import json

def check_jita_characters():
    with open('../test_data/jita.txt', 'r', encoding='utf-8') as f:
        jita_names = [line.strip() for line in f if line.strip()]
    
    with open('../test_data/char_data/extracted_characters.json', 'r', encoding='utf-8') as f:
        all_chars = json.load(f)
    
    jita_names_set = set(jita_names)
    
    print(f"Jita characters: {len(jita_names)}")
    print(f"Total character dataset: {len(all_chars)}")
    print("\nMatch rates by last_active year filter:")
    print("Year | Characters | Found | Match Rate")
    print("-" * 40)
    
    for year in range(2005, 2024):
        cutoff = f"{year}-01-01"
        filtered_chars = [char for char in all_chars 
                         if char.get('last_active') and char.get('last_active') >= cutoff]
        
        filtered_names = {char.get('name') for char in filtered_chars if char.get('name')}
        found = len([name for name in jita_names if name in filtered_names])
        match_rate = found / len(jita_names) * 100
        
        print(f"{year} | {len(filtered_chars):9,} | {found:5} | {match_rate:6.1f}%")

if __name__ == "__main__":
    check_jita_characters()
