
import asyncio
import aiohttp
import json

async def get_ship_types_esi():
    """Get all ship types by querying the ships category directly"""
    try:
        async with aiohttp.ClientSession() as session:
            # Get ship groups from category 6 (Ships)
            category_url = "https://esi.evetech.net/latest/universe/categories/6/"
            async with session.get(category_url) as response:
                if response.status != 200:
                    print(f"Failed to get ship category: {response.status}")
                    return {}
                
                category_data = await response.json()
                ship_group_ids = category_data.get('groups', [])
                print(f"Found {len(ship_group_ids)} ship groups")
            
            # Get all types from each ship group
            all_ship_type_ids = []
            for group_id in ship_group_ids:
                group_url = f"https://esi.evetech.net/latest/universe/groups/{group_id}/"
                async with session.get(group_url) as response:
                    if response.status == 200:
                        group_data = await response.json()
                        type_ids = group_data.get('types', [])
                        all_ship_type_ids.extend(type_ids)
                        print(f"Group {group_data.get('name', group_id)}: {len(type_ids)} types")
            
            print(f"Processing {len(all_ship_type_ids)} ship type IDs...")
            
            # Get detailed info for all ship types
            ship_data = {}
            chunk_size = 100
            
            for i in range(0, len(all_ship_type_ids), chunk_size):
                chunk = all_ship_type_ids[i:i + chunk_size]
                chunk_data = await _get_types_info_batch(session, chunk)
                
                for type_id, type_info in chunk_data.items():
                    group_name = await _get_group_name(session, type_info.get('group_id'))
                    ship_data[type_info['name']] = {
                        'type_id': type_id,
                        'group_id': type_info.get('group_id'),
                        'group_name': group_name
                    }
                
                print(f"Processed {min(i + chunk_size, len(all_ship_type_ids))}/{len(all_ship_type_ids)} types")
            
            print(f"Retrieved {len(ship_data)} ship types")
            return ship_data
            
    except Exception as e:
        print(f"Error fetching ship types: {e}")
        return {}

async def _get_types_info_batch(session, type_ids):
    """Get type information for a batch of type IDs"""
    tasks = []
    for type_id in type_ids:
        url = f"https://esi.evetech.net/latest/universe/types/{type_id}/"
        tasks.append(_fetch_type_info(session, type_id, url))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    type_data = {}
    for type_id, result in zip(type_ids, results):
        if not isinstance(result, Exception) and result:
            type_data[type_id] = result
    
    return type_data

async def _fetch_type_info(session, type_id, url):
    """Fetch individual type info"""
    try:
        async with session.get(url, timeout=10) as response:
            if response.status == 200:
                return await response.json()
    except Exception:
        pass
    return None

async def _get_group_name(session, group_id):
    """Get group name from group ID"""
    if not group_id:
        return "Unknown"
        
    try:
        url = f"https://esi.evetech.net/latest/universe/groups/{group_id}/"
        async with session.get(url, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('name', 'Unknown')
    except Exception:
        pass
    
    return "Unknown"

async def build_ship_data():
    ships = await get_ship_types_esi()
    
    # Save to file
    with open('ships.json', 'w') as f:
        json.dump(ships, f, indent=2)
    
    # Print some examples by category
    categories = {}
    for ship_name, info in ships.items():
        cat = info['group_name']
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(ship_name)
    
    print(f"\nFound {len(categories)} ship categories:")
    for cat, ship_list in sorted(categories.items()):
        print(f"{cat}: {len(ship_list)} ships")
        print(f"  Examples: {', '.join(ship_list[:3])}")

if __name__ == "__main__":
    asyncio.run(build_ship_data())
