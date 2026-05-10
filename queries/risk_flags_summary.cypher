MATCH (c:Company)-[:REGISTERED_AT]->(a:Address)
WITH a, count(DISTINCT c) AS company_count, collect(DISTINCT c.name)[0..5] AS sample
WHERE company_count >= 50
RETURN a.full_address AS address, company_count, sample
ORDER BY company_count DESC LIMIT 50;