#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from etl.stage_load import get_database_url, load_hmlr_csv
import psycopg

with psycopg.connect(get_database_url()) as conn:
    load_hmlr_csv(conn, 'ccod', 'stg_ccod_titles')
    load_hmlr_csv(conn, 'ocod', 'stg_ocod_titles')