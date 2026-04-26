import os

import pytest
from sqlalchemy import create_engine, text


def test_postgres_postgis():
    url = os.getenv("DATABASE_URL", "postgresql://plottr:plottr@localhost:5432/plottr")
    engine = create_engine(url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT PostGIS_Version()"))
        assert result.fetchone()[0] is not None


def test_neo4j_ping():
    from neo4j import GraphDatabase
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "plottr_secret")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as session:
        result = session.run("RETURN 1 AS n")
        assert result.single()["n"] == 1
    driver.close()
