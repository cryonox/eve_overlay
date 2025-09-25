import os
import time
import gzip
import bz2
import lzma
import zlib
from pathlib import Path
import json

try:
    import py7zr
    HAS_7ZIP = True
except ImportError:
    HAS_7ZIP = False
    print("py7zr not available - install with: pip install py7zr")

try:
    import brotli
    HAS_BROTLI = True
except ImportError:
    HAS_BROTLI = False
    print("brotli not available - install with: pip install brotli")

def get_file_size(fpath):
    return os.path.getsize(fpath)

def test_compression_method(data, compress_fn, decompress_fn, method_name, params=None):
    param_str = f" ({params})" if params else ""
    
    start_time = time.perf_counter()
    compressed = compress_fn(data)
    compress_time = time.perf_counter() - start_time
    
    start_time = time.perf_counter()
    decompressed = decompress_fn(compressed)
    decompress_time = time.perf_counter() - start_time
    
    original_size = len(data)
    compressed_size = len(compressed)
    ratio = compressed_size / original_size
    
    return {
        'method': method_name + param_str,
        'original_size': original_size,
        'compressed_size': compressed_size,
        'ratio': ratio,
        'compress_time': compress_time,
        'decompress_time': decompress_time,
        'total_time': compress_time + decompress_time
    }

def test_7zip_method(data, filters=None):
    import tempfile
    import os
    
    with tempfile.NamedTemporaryFile(suffix='.7z', delete=False) as tmp_file:
        tmp_path = tmp_file.name
    
    try:
        start_time = time.perf_counter()
        with py7zr.SevenZipFile(tmp_path, 'w', filters=filters) as archive:
            archive.writestr(data, "data.bin")
        compress_time = time.perf_counter() - start_time
        
        compressed_size = os.path.getsize(tmp_path)
        
        start_time = time.perf_counter()
        with py7zr.SevenZipFile(tmp_path, 'r') as archive:
            with tempfile.TemporaryDirectory() as extract_dir:
                archive.extractall(path=extract_dir)
                with open(os.path.join(extract_dir, "data.bin"), 'rb') as f:
                    decompressed = f.read()
        decompress_time = time.perf_counter() - start_time
        
        return compressed_size, compress_time, decompress_time
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

def test_all_compression():
    bin_file = Path('../test_data/char_data/characters.bin')
    if not bin_file.exists():
        print(f"File not found: {bin_file}")
        return
    
    with open(bin_file, 'rb') as f:
        data = f.read()
    
    print(f"Testing compression on {bin_file.name}")
    print(f"Original size: {len(data):,} bytes")
    print()
    print(f"{'Method':<20} {'Ratio':<8} {'Size':<12} {'Comp(ms)':<10} {'Decomp(ms)':<12} {'Total(ms)':<10}")
    print("-" * 80)
    
    results = []
    
    # 7zip with different compression methods (if available)
    if HAS_7ZIP:
        # Default LZMA
        try:
            compressed_size, compress_time, decompress_time = test_7zip_method(data)
            res = {
                'method': '7zip (default)',
                'original_size': len(data),
                'compressed_size': compressed_size,
                'ratio': compressed_size / len(data),
                'compress_time': compress_time,
                'decompress_time': decompress_time,
                'total_time': compress_time + decompress_time
            }
            results.append(res)
            print(f"{res['method']:<20} {res['ratio']:.3f}    {res['compressed_size']:>8,} "
                  f"{res['compress_time']*1000:>8.1f}   {res['decompress_time']*1000:>10.1f}   "
                  f"{res['total_time']*1000:>8.1f}")
        except Exception as e:
            print(f"7zip default failed: {e}")
        
        # LZMA2 with different compression levels
        for level in [1, 5, 9]:
            try:
                filters = [{"id": py7zr.FILTER_LZMA2, "preset": level}]
                compressed_size, compress_time, decompress_time = test_7zip_method(data, filters)
                res = {
                    'method': f'7zip LZMA2 (level={level})',
                    'original_size': len(data),
                    'compressed_size': compressed_size,
                    'ratio': compressed_size / len(data),
                    'compress_time': compress_time,
                    'decompress_time': decompress_time,
                    'total_time': compress_time + decompress_time
                }
                results.append(res)
                print(f"{res['method']:<20} {res['ratio']:.3f}    {res['compressed_size']:>8,} "
                      f"{res['compress_time']*1000:>8.1f}   {res['decompress_time']*1000:>10.1f}   "
                      f"{res['total_time']*1000:>8.1f}")
            except Exception as e:
                print(f"7zip LZMA2 level={level} failed: {e}")
    
    # brotli with different quality levels (if available)
    if HAS_BROTLI:
        for quality in [1, 6, 11]:
            res = test_compression_method(
                data,
                lambda d, q=quality: brotli.compress(d, quality=q),
                brotli.decompress,
                'brotli',
                f'quality={quality}'
            )
            results.append(res)
            print(f"{res['method']:<20} {res['ratio']:.3f}    {res['compressed_size']:>8,} "
                  f"{res['compress_time']*1000:>8.1f}   {res['decompress_time']*1000:>10.1f}   "
                  f"{res['total_time']*1000:>8.1f}")
    
    # gzip with different compression levels
    for level in [1, 6, 9]:
        res = test_compression_method(
            data,
            lambda d, l=level: gzip.compress(d, compresslevel=l),
            gzip.decompress,
            'gzip',
            f'level={level}'
        )
        results.append(res)
        print(f"{res['method']:<20} {res['ratio']:.3f}    {res['compressed_size']:>8,} "
              f"{res['compress_time']*1000:>8.1f}   {res['decompress_time']*1000:>10.1f}   "
              f"{res['total_time']*1000:>8.1f}")
    
    # bz2 with different compression levels
    for level in [1, 6, 9]:
        res = test_compression_method(
            data,
            lambda d, l=level: bz2.compress(d, compresslevel=l),
            bz2.decompress,
            'bz2',
            f'level={level}'
        )
        results.append(res)
        print(f"{res['method']:<20} {res['ratio']:.3f}    {res['compressed_size']:>8,} "
              f"{res['compress_time']*1000:>8.1f}   {res['decompress_time']*1000:>10.1f}   "
              f"{res['total_time']*1000:>8.1f}")
    
    # lzma/xz with different presets
    for preset in [0, 3, 6, 9]:
        res = test_compression_method(
            data,
            lambda d, p=preset: lzma.compress(d, preset=p),
            lzma.decompress,
            'lzma',
            f'preset={preset}'
        )
        results.append(res)
        print(f"{res['method']:<20} {res['ratio']:.3f}    {res['compressed_size']:>8,} "
              f"{res['compress_time']*1000:>8.1f}   {res['decompress_time']*1000:>10.1f}   "
              f"{res['total_time']*1000:>8.1f}")
    
    # zlib with different compression levels
    for level in [1, 6, 9]:
        res = test_compression_method(
            data,
            lambda d, l=level: zlib.compress(d, level=l),
            zlib.decompress,
            'zlib',
            f'level={level}'
        )
        results.append(res)
        print(f"{res['method']:<20} {res['ratio']:.3f}    {res['compressed_size']:>8,} "
              f"{res['compress_time']*1000:>8.1f}   {res['decompress_time']*1000:>10.1f}   "
              f"{res['total_time']*1000:>8.1f}")
    
    # Sort by compression ratio for final summary
    results.sort(key=lambda x: x['ratio'])
    
    print("\n" + "="*80)
    print("FINAL SUMMARY (sorted by compression ratio):")
    print("="*80)
    
    for res in results:
        print(f"{res['method']:<20} {res['ratio']:.3f}    {res['compressed_size']:>8,} "
              f"{res['compress_time']*1000:>8.1f}   {res['decompress_time']*1000:>10.1f}   "
              f"{res['total_time']*1000:>8.1f}")
    
    # Find best by different criteria
    best_ratio = min(results, key=lambda x: x['ratio'])
    best_speed = min(results, key=lambda x: x['total_time'])
    best_compress_speed = min(results, key=lambda x: x['compress_time'])
    
    print("\nBest performers:")
    print(f"Best compression ratio: {best_ratio['method']} ({best_ratio['ratio']:.3f})")
    print(f"Fastest overall: {best_speed['method']} ({best_speed['total_time']*1000:.1f}ms)")
    print(f"Fastest compression: {best_compress_speed['method']} ({best_compress_speed['compress_time']*1000:.1f}ms)")
    
    # Save detailed results
    with open('compression_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nDetailed results saved to compression_results.json")

if __name__ == "__main__":
    test_all_compression()
