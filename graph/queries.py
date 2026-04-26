"""Cypher query helpers for the Plottr graph layer."""
from typing import Any

from neo4j import Driver


def merge_company(driver: Driver, props: dict[str, Any]) -> None:
    cypher = """
    MERGE (c:Company {company_number: $company_number})
    SET c += $props
    """
    with driver.session() as s:
        s.run(cypher, company_number=props["company_number"], props=props)


def merge_title(driver: Driver, props: dict[str, Any]) -> None:
    cypher = """
    MERGE (t:Title {title_number: $title_number})
    SET t += $props
    """
    with driver.session() as s:
        s.run(cypher, title_number=props["title_number"], props=props)


def merge_owns(driver: Driver, company_number: str, title_number: str) -> None:
    cypher = """
    MATCH (c:Company {company_number: $company_number})
    MATCH (t:Title {title_number: $title_number})
    MERGE (c)-[:OWNS]->(t)
    """
    with driver.session() as s:
        s.run(cypher, company_number=company_number, title_number=title_number)


def merge_person(driver: Driver, name: str, props: dict[str, Any] | None = None) -> None:
    cypher = """
    MERGE (p:Person {name: $name})
    SET p += $props
    """
    with driver.session() as s:
        s.run(cypher, name=name, props=props or {})


def merge_officer_of(driver: Driver, person_name: str, company_number: str, role: str) -> None:
    cypher = """
    MATCH (p:Person {name: $person_name})
    MATCH (c:Company {company_number: $company_number})
    MERGE (p)-[:OFFICER_OF {role: $role}]->(c)
    """
    with driver.session() as s:
        s.run(cypher, person_name=person_name, company_number=company_number, role=role)


def merge_psc_of(driver: Driver, person_name: str, company_number: str, nature_of_control: list[str]) -> None:
    cypher = """
    MATCH (p:Person {name: $person_name})
    MATCH (c:Company {company_number: $company_number})
    MERGE (p)-[:PSC_OF {nature_of_control: $noc}]->(c)
    """
    with driver.session() as s:
        s.run(cypher, person_name=person_name, company_number=company_number, noc=nature_of_control)


def get_ownership_chain(driver: Driver, title_number: str) -> list[dict]:
    cypher = """
    MATCH path = (e)-[:OWNS|PSC_OF|OFFICER_OF*1..5]->(t:Title {title_number: $title_number})
    RETURN path
    """
    with driver.session() as s:
        result = s.run(cypher, title_number=title_number)
        return [r.data() for r in result]
