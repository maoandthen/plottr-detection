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


def merge_owned_by(driver: Driver, title_number: str, owner_id: str, props: dict[str, Any]) -> None:
    cypher = """
    MATCH (t:Title {title_number: $title_number})
    MATCH (o {id: $owner_id})
    MERGE (t)-[r:OWNED_BY]->(o)
    SET r += $props
    """
    with driver.session() as s:
        s.run(cypher, title_number=title_number, owner_id=owner_id, props=props)


def merge_person(driver: Driver, person_id: str, props: dict[str, Any] | None = None) -> None:
    cypher = """
    MERGE (p:Person {person_id: $person_id})
    SET p += $props
    """
    with driver.session() as s:
        s.run(cypher, person_id=person_id, props=props or {})


def merge_officer_of(driver: Driver, person_id: str, company_number: str, role: str,
                     appointed_on: str | None = None, resigned_on: str | None = None) -> None:
    cypher = """
    MATCH (p:Person {person_id: $person_id})
    MATCH (c:Company {company_number: $company_number})
    MERGE (p)-[r:OFFICER_OF {role: $role}]->(c)
    SET r.appointed_on = $appointed_on, r.resigned_on = $resigned_on
    """
    with driver.session() as s:
        s.run(cypher, person_id=person_id, company_number=company_number,
              role=role, appointed_on=appointed_on, resigned_on=resigned_on)


def merge_psc_of(driver: Driver, subject_id: str, company_number: str,
                 nature_of_control: list[str],
                 notified_on: str | None = None, ceased_on: str | None = None) -> None:
    cypher = """
    MATCH (s {id: $subject_id})
    MATCH (c:Company {company_number: $company_number})
    MERGE (s)-[r:PSC_OF]->(c)
    SET r.nature_of_control = $noc, r.notified_on = $notified_on, r.ceased_on = $ceased_on
    """
    with driver.session() as s:
        s.run(cypher, subject_id=subject_id, company_number=company_number,
              noc=nature_of_control, notified_on=notified_on, ceased_on=ceased_on)


def find_ultimate_psc(driver: Driver, company_number: str) -> list[dict]:
    """Recursive traversal up PSC_OF chain, max 10 hops."""
    cypher = """
    MATCH path = (p:Person)-[:PSC_OF*1..10]->(c:Company {company_number: $company_number})
    UNWIND relationships(path) AS rel
    WITH p, rel, length(path) AS depth
    RETURN DISTINCT
        p.person_id AS person_id,
        p.full_name AS name,
        rel.nature_of_control AS nature_of_control,
        depth
    ORDER BY depth
    """
    with driver.session() as s:
        result = s.run(cypher, company_number=company_number)
        return [r.data() for r in result]


def titles_owned_by_company(driver: Driver, company_number: str) -> list[dict]:
    """Returns all Title nodes reachable via OWNED_BY from a company."""
    cypher = """
    MATCH (t:Title)-[:OWNED_BY]->(c:Company {company_number: $company_number})
    RETURN t.title_number AS title_number, t.tenure AS tenure,
           t.price_paid AS price_paid, t.date_registered AS date_registered,
           t.source AS source
    """
    with driver.session() as s:
        result = s.run(cypher, company_number=company_number)
        return [r.data() for r in result]


def three_hop_ownership(driver: Driver, title_number: str) -> dict:
    """Full 3-hop subgraph: title → company → ultimate owner."""
    cypher = """
    MATCH path = (t:Title {title_number: $title_number})-[:OWNED_BY*1..3]->(owner)
    RETURN
        [n IN nodes(path) | {labels: labels(n), properties: properties(n)}] AS nodes,
        [r IN relationships(path) | {type: type(r), properties: properties(r)}] AS rels
    """
    with driver.session() as s:
        result = s.run(cypher, title_number=title_number)
        rows = [r.data() for r in result]
        all_nodes = {str(n["properties"]): n for row in rows for n in row["nodes"]}
        all_rels = [r for row in rows for r in row["rels"]]
        return {"nodes": list(all_nodes.values()), "relationships": all_rels}


def person_network(driver: Driver, person_id: str) -> dict:
    """All companies where person is officer or PSC, all titles linked to those companies."""
    cypher = """
    MATCH (p:Person {person_id: $person_id})
    OPTIONAL MATCH (p)-[o:OFFICER_OF]->(c1:Company)
    OPTIONAL MATCH (p)-[psc:PSC_OF]->(c2:Company)
    WITH p, collect(DISTINCT c1) + collect(DISTINCT c2) AS companies
    UNWIND companies AS c
    OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(c)
    RETURN
        p.person_id AS person_id,
        p.full_name AS full_name,
        collect(DISTINCT {company_number: c.company_number, company_name: c.company_name}) AS companies,
        collect(DISTINCT {title_number: t.title_number, tenure: t.tenure}) AS titles
    """
    with driver.session() as s:
        result = s.run(cypher, person_id=person_id)
        rows = [r.data() for r in result]
        return rows[0] if rows else {}
