import json
import sys
import time
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List

class CharacterDownloader:
    def __init__(self, batch_size: int = 1000, chars_per_file: int = 10000, 
                 batch_dir: str = "batches", output_file: str = "characters.json",
                 rate_limit_delay: float = 1.0):
        self.batch_size = batch_size
        self.chars_per_file = chars_per_file
        self.batch_dir = Path(batch_dir)
        self.output_file = output_file
        self.rate_limit_delay = rate_limit_delay
        self.resume_batch = 0
        self.resume_after_id = None
        self.file_count = 0
        self.current_batch_chars = []
        
    def ensure_batch_dir(self):
        self.batch_dir.mkdir(exist_ok=True)
        
    def get_collection_info(self) -> Optional[Dict[str, Any]]:
        # Placeholder - implement based on your API
        return {"estimatedCount": 100000}
        
    def download_batch(self, after_id: Optional[str]) -> Optional[Dict[str, Any]]:
        # Placeholder - implement your API call here
        # Return format: {"data": [{"_id": "...", "name": "...", ...}]}
        return {"data": []}
        
    def add_chars_to_batch(self, chars: List[Dict[str, Any]]):
        self.current_batch_chars.extend(chars)
        if len(self.current_batch_chars) >= self.chars_per_file:
            self.save_batch_file()
            
    def save_batch_file(self):
        if not self.current_batch_chars:
            return
        batch_file = self.batch_dir / f"batch_{self.file_count:04d}.json"
        with open(batch_file, 'w') as f:
            json.dump(self.current_batch_chars, f)
        self.current_batch_chars = []
        self.file_count += 1
        
    def save_progress_state(self, batch_count: int, after_id: str, total_downloaded: int):
        state = {
            "batch_count": batch_count,
            "after_id": after_id,
            "total_downloaded": total_downloaded
        }
        with open("progress.json", 'w') as f:
            json.dump(state, f)
            
    def combine_batch_files(self) -> bool:
        all_chars = []
        for batch_file in sorted(self.batch_dir.glob("batch_*.json")):
            with open(batch_file) as f:
                all_chars.extend(json.load(f))
        
        with open(self.output_file, 'w') as f:
            json.dump(all_chars, f)
        return True

    def download_all_characters(self) -> bool:
        self.ensure_batch_dir()
        
        info = self.get_collection_info()
        if not info:
            print("Failed to get collection info")
            return False
        
        estimated_count = info.get("estimatedCount", 0)
        print(f"Estimated characters: {estimated_count:,}")
        
        batch_count = self.resume_batch
        after_id = self.resume_after_id
        total_downloaded = 0
        
        if batch_count > 0:
            print(f"Resuming from batch {batch_count}, after_id: {after_id}")
        
        try:
            while True:
                print(f"Downloading batch {batch_count}...")
                
                batch_data = self.download_batch(after_id)
                if not batch_data or not batch_data.get("data"):
                    print("No more data to download")
                    break
                
                chars = batch_data["data"]
                total_downloaded += len(chars)
                
                self.add_chars_to_batch(chars)
                
                if chars:
                    after_id = chars[-1].get("_id")
                    self.save_progress_state(batch_count, after_id, total_downloaded)
                
                print(f"Downloaded {len(chars)} characters (total: {total_downloaded:,})")
                
                batch_count += 1
                time.sleep(self.rate_limit_delay)
                
        except KeyboardInterrupt:
            print(f"\nInterrupted. Progress saved at batch {batch_count}")
            return False
        except Exception as e:
            print(f"Error during download: {e}")
            return False
        
        if self.current_batch_chars:
            self.save_batch_file()
        
        print(f"Download complete. Total characters: {total_downloaded:,}")
        print("Combining batch files...")
        
        return self.combine_batch_files()

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Download characters')
    parser.add_argument('--resume', nargs=2, metavar=('BATCH', 'AFTER_ID'),
                       help='Resume from batch number and after_id')
    parser.add_argument('--batch-size', type=int, default=1000,
                       help='Batch size for downloads')
    parser.add_argument('--output', default='characters.json',
                       help='Output file name')
    
    args = parser.parse_args()
    
    downloader = CharacterDownloader(
        batch_size=args.batch_size,
        output_file=args.output
    )
    
    if args.resume:
        downloader.resume_batch = int(args.resume[0])
        downloader.resume_after_id = args.resume[1]
    
    success = downloader.download_all_characters()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
