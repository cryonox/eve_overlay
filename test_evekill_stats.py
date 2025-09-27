import asyncio
from esi import ESIClient
from evekill import EveKillClient

async def test_evekill_stats():
    with open('test_data/init.txt', 'r', encoding='utf-8') as f:
        names = [line.strip() for line in f if line.strip()][:20]
    
    print(f"Testing with {len(names)} names")
    
    esi = ESIClient()
    evekill = EveKillClient()
    
    print("Resolving names to IDs...")
    name_to_id = await esi.names_to_ids(names)
    char_ids = [name_to_id.get(name) for name in names if name_to_id.get(name)]
    
    print(f"Resolved {len(char_ids)} character IDs")
    
    print("Fetching EveKill stats...")
    for name in names:
        char_id = name_to_id.get(name)
        if char_id:
            stats = await evekill.get_char_short_stats(char_id)
            print(f"{name} ({char_id}): {stats}")
        else:
            print(f"{name}: Not found")

if __name__ == "__main__":
    asyncio.run(test_evekill_stats())
