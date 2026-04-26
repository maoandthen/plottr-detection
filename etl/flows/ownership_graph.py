"""
Prefect flow: ingest all data sources and build the ownership graph.

Sequence: CCOD → OCOD → Companies House → Charity Commission
Gate: Companies House tasks require COMPANIES_HOUSE_API_KEY in env.
"""
from prefect import flow, task, get_run_logger
import os


@task(name="ingest-ccod")
def ingest_ccod():
    logger = get_run_logger()
    logger.info("Starting CCOD ingest (M1 skeleton — not yet wired to DB)")
    # M2+: call extract.download(), transform.transform(), load.load()
    raise NotImplementedError("CCOD ingest not yet implemented (M2+)")


@task(name="ingest-ocod")
def ingest_ocod():
    logger = get_run_logger()
    logger.info("Starting OCOD ingest (M1 skeleton — not yet wired to DB)")
    raise NotImplementedError("OCOD ingest not yet implemented (M2+)")


@task(name="ingest-companies-house")
def ingest_companies_house():
    logger = get_run_logger()
    key = os.getenv("COMPANIES_HOUSE_API_KEY", "")
    if not key or key == "REPLACE_ME":
        raise EnvironmentError("Requires COMPANIES_HOUSE_API_KEY in .env — skipping CH ingest")
    raise NotImplementedError("CH ingest not yet implemented (M2+)")


@task(name="ingest-charity-commission")
def ingest_charity_commission():
    logger = get_run_logger()
    logger.info("Starting Charity Commission ingest (M1 skeleton)")
    raise NotImplementedError("Charity Commission ingest not yet implemented (M2+)")


@flow(name="ownership-graph", log_prints=True)
def ownership_graph_flow():
    """Full ownership graph ETL pipeline."""
    ingest_ccod()
    ingest_ocod()
    ingest_companies_house()
    ingest_charity_commission()


if __name__ == "__main__":
    ownership_graph_flow()
