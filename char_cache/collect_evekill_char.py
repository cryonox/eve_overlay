import asyncio
import sys
sys.path.append('..')
from evekill import EveKillClient

async def collect_evekill_chars():
    print("Starting EveKill characters export...")
    
    evekill = EveKillClient()
    
    await evekill.export_ek_characters(
        batch_location='../test_data/ek_batches_chars/',
        batch_size=100000,
        dst_json='../test_data/char_data/evekill_chars_export.json'
    )
    
    print("EveKill characters export complete!")

if __name__ == "__main__":
    asyncio.run(collect_evekill_chars())
