import asyncio
import sys
sys.path.append('..')
from evekill import EveKillClient

async def collect_evekill_stats():
    print("Starting EveKill stats export...")
    
    evekill = EveKillClient()
    
    await evekill.export_ek_stats(
        batch_location='../test_data/ek_batches_stats/',
        batch_size=100000,
        dst_json='../test_data/char_data/evekill_stats_export.json'
    )
    
    print("EveKill stats export complete!")

if __name__ == "__main__":
    asyncio.run(collect_evekill_stats())
