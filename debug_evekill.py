import asyncio
import aiohttp
import json

TEST_CHAR_IDS = [2113024536, 93265215, 2114794365]
TEST_CHAR_NAMES = ["Gideon Zendikar", "Tikktokk Topp", "Hy Wansen"]

async def test_url(url, label=""):
    headers = {'User-Agent': 'Eve Overlay Debug'}
    print(f"\n--- {label} ---")
    print(f"URL: {url}")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=30) as resp:
                print(f"Status: {resp.status}")
                text = await resp.text()
                print(f"Response length: {len(text)} chars")
                print(f"Response (first 800 chars): {text[:800]}")
                if resp.status == 200:
                    try:
                        data = json.loads(text)
                        print(f"Parsed JSON keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                    except json.JSONDecodeError as e:
                        print(f"JSON decode error: {e}")
        except Exception as e:
            print(f"Exception: {type(e).__name__}: {e}")

async def test_single_request(char_id):
    url = f"https://eve-kill.com/api/stats/character_id/{char_id}?dataType=basic&days=0"
    headers = {'User-Agent': 'Eve Overlay Debug'}

    print(f"\n--- Testing char_id: {char_id} ---")
    print(f"URL: {url}")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=30) as resp:
                print(f"Status: {resp.status}")
                print(f"Headers: {dict(resp.headers)}")
                text = await resp.text()
                print(f"Response length: {len(text)} chars")
                print(f"Response (first 500 chars): {text[:500]}")

                if resp.status == 200:
                    try:
                        data = json.loads(text)
                        print(f"Parsed JSON keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                        if isinstance(data, dict):
                            print(f"dangerRatio: {data.get('dangerRatio')}")
                            print(f"kills: {data.get('kills')}")
                            print(f"losses: {data.get('losses')}")
                    except json.JSONDecodeError as e:
                        print(f"JSON decode error: {e}")
        except aiohttp.ClientError as e:
            print(f"ClientError: {type(e).__name__}: {e}")
        except asyncio.TimeoutError:
            print("TimeoutError: Request timed out")
        except Exception as e:
            print(f"Exception: {type(e).__name__}: {e}")

async def test_api_endpoint():
    url = "https://eve-kill.com/api"
    print(f"\n--- Testing API base endpoint ---")
    print(f"URL: {url}")
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers={'User-Agent': 'Eve Overlay Debug'}, timeout=30) as resp:
                print(f"Status: {resp.status}")
                text = await resp.text()
                print(f"Response (first 300 chars): {text[:300]}")
        except Exception as e:
            print(f"Exception: {type(e).__name__}: {e}")

async def test_export_endpoint():
    url = "https://eve-kill.com/api/export"
    print(f"\n--- Testing export endpoint ---")
    print(f"URL: {url}")
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers={'User-Agent': 'Eve Overlay Debug'}, timeout=30) as resp:
                print(f"Status: {resp.status}")
                text = await resp.text()
                print(f"Response (first 500 chars): {text[:500]}")
        except Exception as e:
            print(f"Exception: {type(e).__name__}: {e}")

def check_local_stats():
    print("\n--- Checking local stats batch files ---")
    fpath = "test_data/ek_batches_stats/batch_0000.json"
    with open(fpath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"Total records in first batch: {len(data)}")
    print(f"First record keys: {list(data[0].keys())}")
    print(f"Sample record with kills > 0:")
    for rec in data[:1000]:
        if rec.get('kills', 0) > 0:
            print(json.dumps(rec, indent=2))
            break

async def main():
    print("=" * 60)
    print("EVE-KILL API DEBUG")
    print("=" * 60)

    check_local_stats()

    char_id = TEST_CHAR_IDS[0]

    print("\n--- Testing API endpoints ---")
    urls_to_try = [
        (f"https://eve-kill.com/api/stats/character_id/{char_id}?dataType=basic&days=0", "Current URL (broken)"),
        (f"https://eve-kill.com/api/characters/{char_id}", "/characters/id"),
        ("https://eve-kill.com/api/export", "export collections"),
    ]

    for url, label in urls_to_try:
        await test_url(url, label)
        await asyncio.sleep(0.3)

    print("\n" + "=" * 60)
    print("DIAGNOSIS")
    print("=" * 60)
    print("ISSUE: EVE-KILL API has changed!")
    print("1. Stats endpoint /api/stats/character_id/{id} returns 404")
    print("2. Export API no longer has 'stats' collection")
    print("   Available: killmails, characters, corporations, alliances, types, prices")
    print("3. Local batch files have old stats but no 'dangerRatio' field")
    print("\nRECOMMENDATION: Switch to zkillboard stats provider or")
    print("   compute stats from killmails if needed")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
