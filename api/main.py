import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import create_engine, text

from api.routers import ownership, search


def _check_postgres() -> bool:
    try:
        url = os.getenv("DATABASE_URL", "postgresql://plottr:plottr@localhost:5432/plottr")
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _check_neo4j() -> bool:
    try:
        from neo4j import GraphDatabase
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "plottr_secret")
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            session.run("RETURN 1 AS n").single()
        driver.close()
        return True
    except Exception:
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Plottr Detection API", version="0.1.0", lifespan=lifespan)

app.include_router(ownership.router)
app.include_router(search.router)


@app.get("/")
def root():
    return {"service": "plottr-detection", "version": "0.1.0"}


@app.get("/health")
def health():
    postgres_ok = _check_postgres()
    neo4j_ok = _check_neo4j()
    return {
        "status": "ok",
        "postgres": postgres_ok,
        "neo4j": neo4j_ok,
    }
