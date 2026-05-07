#!/usr/bin/env python3
"""
Bulk download orchestration for M1 pipeline.
Downloads all six bulk sources to $DATA_DIR/raw/ using existing connector logic.
"""

import os
import time
from pathlib import Path
import urllib.request
import urllib.error

# Import existing connector extract modules
from etl.connectors.companies_house import extract as ch_extract
from etl.connectors.hmlr_ccod import extract as ccod_extract  
from etl.connectors.hmlr_ocod import extract as ocod_extract
from etl.connectors.charity_commission import extract as cc_extract


def get_data_dir() -> Path:
    """Get DATA_DIR from environment, default to /Volumes/PlottrData"""
    data_dir = os.getenv("DATA_DIR", "/Volumes/PlottrData")
    return Path(data_dir)


def download_with_resume(target_path: Path, download_fn, min_size_mb: float = 1.0):
    """Skip download if target exists with reasonable size. Otherwise call download_fn."""
    if target_path.exists():
        size_mb = target_path.stat().st_size / 1e6
        if size_mb >= min_size_mb:
            print(f"  ✓ Skipping (already exists, {size_mb:.1f}MB): {target_path}")
            return target_path
        else:
            print(f"  ⚠ Existing file too small ({size_mb:.1f}MB), re-downloading")
    return download_fn()


def check_url_exists(url: str) -> bool:
    """Verify URL exists via HEAD request. Hard error on 404 or empty response."""
    print(f"  Checking URL: {url}")
    try:
        req = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status == 200:
                content_length = response.headers.get('Content-Length')
                if content_length and int(content_length) > 0:
                    print(f"  ✓ URL exists ({int(content_length)} bytes)")
                    return True
                else:
                    print(f"  ✓ URL exists (streaming/unknown size)")
                    return True
            else:
                raise RuntimeError(f"URL returned status {response.status}: {url}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(f"URL not found (404): {url}") from e
        else:
            raise RuntimeError(f"URL check failed ({e.code}): {url}") from e
    except Exception as e:
        raise RuntimeError(f"URL check failed: {url} - {e}") from e


def download_companies_house_data(raw_dir: Path) -> dict:
    """Download CH company snapshot, officers, and PSC data."""
    ch_dir = raw_dir / "companies_house"
    print("\n=== Companies House Downloads ===")
    
    results = {}
    start_time = time.time()
    
    # 1. Company snapshot
    print("\n1. Company Snapshot:")
    company_path = ch_extract.download_company_snapshot(ch_dir / "snapshot")
    results['company_snapshot'] = {
        'path': company_path,
        'size_mb': company_path.stat().st_size / 1e6
    }
    
    # 2. Officers data unavailable as bulk download — handled via API in M1.5 incremental enrichment job, see TODO.
    
    # 3. PSC (single or multi-part)
    print("\n3. PSC Data:")
    psc_paths = ch_extract.download_psc_snapshot(ch_dir / "psc")
    total_size = sum(p.stat().st_size for p in psc_paths)
    results['psc'] = {
        'paths': psc_paths,
        'parts': len(psc_paths),
        'total_size_mb': total_size / 1e6
    }
    
    results['total_time_sec'] = time.time() - start_time
    return results


def download_land_registry_data(raw_dir: Path) -> dict:
    """Download HMLR CCOD and OCOD data."""
    print("\n=== Land Registry Downloads ===")
    
    results = {}
    start_time = time.time()
    
    # CCOD
    print("\n1. CCOD (Corporate Ownership):")
    ccod_target = raw_dir / "land_registry" / "ccod_latest.zip"
    ccod_path = download_with_resume(
        ccod_target,
        lambda: ccod_extract.download()
    )
    results['ccod'] = {
        'path': ccod_path,
        'size_mb': ccod_path.stat().st_size / 1e6
    }
    
    # OCOD  
    print("\n2. OCOD (Overseas Corporate Ownership):")
    ocod_target = raw_dir / "land_registry" / "ocod_latest.zip"
    ocod_path = download_with_resume(
        ocod_target,
        lambda: ocod_extract.download()
    )
    results['ocod'] = {
        'path': ocod_path,
        'size_mb': ocod_path.stat().st_size / 1e6
    }
    
    results['total_time_sec'] = time.time() - start_time
    return results


def download_charity_commission_data(raw_dir: Path) -> dict:
    """Download Charity Commission data (placeholder - NotImplementedError expected)."""
    print("\n=== Charity Commission Downloads ===")
    
    # This will raise NotImplementedError per existing code
    try:
        cc_path = cc_extract.download()
        return {
            'charity_commission': {
                'path': cc_path,
                'size_mb': cc_path.stat().st_size / 1e6
            }
        }
    except NotImplementedError as e:
        print(f"Skipping Charity Commission: {e}")
        return {'charity_commission': 'skipped (not implemented)'}


def main():
    """Main download orchestration."""
    print("=== BULK DOWNLOAD ORCHESTRATION ===")
    
    data_dir = get_data_dir()
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Data directory: {data_dir}")
    print(f"Raw directory: {raw_dir}")
    
    total_start_time = time.time()
    all_results = {}
    total_bytes = 0
    
    try:
        # Download all sources
        ch_results = download_companies_house_data(raw_dir)
        all_results['companies_house'] = ch_results
        
        lr_results = download_land_registry_data(raw_dir) 
        all_results['land_registry'] = lr_results
        
        cc_results = download_charity_commission_data(raw_dir)
        all_results['charity_commission'] = cc_results
        
        # Calculate totals
        for source, data in all_results.items():
            if source == 'companies_house':
                total_bytes += data['company_snapshot']['size_mb'] * 1e6
                total_bytes += data['psc']['total_size_mb'] * 1e6
            elif source == 'land_registry':
                total_bytes += data['ccod']['size_mb'] * 1e6
                total_bytes += data['ocod']['size_mb'] * 1e6
        
        total_time = time.time() - total_start_time
        
        # Summary report
        print("\n" + "="*60)
        print("BULK DOWNLOAD COMPLETE")
        print("="*60)
        print(f"Total time: {total_time:.1f} seconds ({total_time/60:.1f} minutes)")
        print(f"Total downloaded: {total_bytes/1e6:.1f} MB ({total_bytes/1e9:.1f} GB)")
        print(f"Average speed: {(total_bytes/1e6)/total_time:.1f} MB/s")
        
        # Per-source breakdown
        for source, data in all_results.items():
            print(f"\n{source.upper()}:")
            if source == 'companies_house':
                print(f"  Company snapshot: {data['company_snapshot']['size_mb']:.1f} MB")
                print(f"  PSC: {data['psc']['parts']} parts, {data['psc']['total_size_mb']:.1f} MB")
                print(f"  Time: {data['total_time_sec']:.1f}s")
            elif source == 'land_registry':
                print(f"  CCOD: {data['ccod']['size_mb']:.1f} MB")
                print(f"  OCOD: {data['ocod']['size_mb']:.1f} MB")
                print(f"  Time: {data['total_time_sec']:.1f}s")
            elif source == 'charity_commission':
                print(f"  Status: {data}")
        
        print("\nBulk downloads successful! ✓")
        
    except Exception as e:
        print(f"\nBULK DOWNLOAD FAILED: {e}")
        raise


if __name__ == "__main__":
    main()