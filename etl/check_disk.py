#!/usr/bin/env python3
"""
Disk space check for bulk downloads.
Verifies ≥150GB free at $DATA_DIR before starting any downloads.
"""

import os
import shutil
import sys
from pathlib import Path


def check_disk_space(min_gb: float = 150.0) -> bool:
    """
    Check if DATA_DIR has sufficient free space.
    Returns True if sufficient, False otherwise.
    Prints actual free space in GB.
    """
    data_dir = os.getenv("DATA_DIR", "/Volumes/PlottrData")
    data_path = Path(data_dir)
    
    if not data_path.exists():
        print(f"ERROR: DATA_DIR does not exist: {data_dir}")
        return False
    
    try:
        _, _, free_bytes = shutil.disk_usage(data_path)
        free_gb = free_bytes / (1024 ** 3)
        
        print(f"Disk space check: {free_gb:.1f}GB available at {data_dir}")
        
        if free_gb < min_gb:
            print(f"ERROR: Insufficient disk space. Need ≥{min_gb}GB, have {free_gb:.1f}GB")
            return False
        
        print(f"✓ Sufficient space ({free_gb:.1f}GB ≥ {min_gb}GB)")
        return True
        
    except OSError as e:
        print(f"ERROR: Cannot check disk space at {data_dir}: {e}")
        return False


def main():
    """Main entry point - exits with code 1 if insufficient space."""
    if not check_disk_space():
        sys.exit(1)
    print("Disk space check passed.")


if __name__ == "__main__":
    main()