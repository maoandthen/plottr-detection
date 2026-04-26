"""Load transformed OCOD DataFrame into Postgres titles table."""
import os

import pandas as pd
from sqlalchemy import create_engine


def load(df: pd.DataFrame) -> int:
    url = os.getenv("DATABASE_URL", "postgresql://plottr:plottr@localhost:5432/plottr")
    engine = create_engine(url)
    df.to_sql("titles", engine, if_exists="append", index=False, method="multi", chunksize=500)
    return len(df)
