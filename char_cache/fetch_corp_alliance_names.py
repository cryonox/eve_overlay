import json
import asyncio
from esi import ESIClient

async def fetch_names():
    with open('test_data/char_data/unique_corps_alliances.json', 'r') as f:
        data = json.load(f)
    
    corp_ids = data['corporations']
    alliance_ids = data['alliances']
    
    print(f"Fetching names for {len(corp_ids)} corps and {len(alliance_ids)} alliances")
    
    esi = ESIClient()
    
    print("Fetching corporation names...")
    corp_names = await esi.ids_to_names(corp_ids)
    
    print("Fetching alliance names...")
    alliance_names = await esi.ids_to_names(alliance_ids)
    
    res = {
        'corporations': {str(id): corp_names.get(id, 'Unknown') for id in corp_ids},
        'alliances': {str(id): alliance_names.get(id, 'Unknown') for id in alliance_ids},
        'corp_count': len(corp_ids),
        'alliance_count': len(alliance_ids)
    }
    
    with open('test_data/char_data/corps_alliances_with_names.json', 'w') as f:
        json.dump(res, f, indent=2)
    
    print(f"Saved names to test_data/char_data/corps_alliances_with_names.json")
    print(f"Resolved {len(corp_names)} corp names, {len(alliance_names)} alliance names")

if __name__ == "__main__":
    asyncio.run(fetch_names())
