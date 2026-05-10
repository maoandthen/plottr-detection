#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from etl.export_for_neo4j_admin import get_db, export_persons_and_psc
with get_db() as conn:
    export_persons_and_psc(conn)