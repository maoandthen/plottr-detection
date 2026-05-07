// Neo4j graph schema for M1 pipeline
// Constraints and indexes for corporate ownership detection

// === CONSTRAINTS ===

// Ensure unique identifiers for each node type
CREATE CONSTRAINT company_number_unique IF NOT EXISTS
FOR (c:Company) REQUIRE c.company_number IS UNIQUE;

CREATE CONSTRAINT title_number_unique IF NOT EXISTS  
FOR (t:Title) REQUIRE t.title_number IS UNIQUE;

CREATE CONSTRAINT person_id_unique IF NOT EXISTS
FOR (p:Person) REQUIRE p.person_id IS UNIQUE;

CREATE CONSTRAINT address_id_unique IF NOT EXISTS
FOR (a:Address) REQUIRE a.address_id IS UNIQUE;

// === INDEXES ===

// Search indexes for common queries
CREATE INDEX company_name_idx IF NOT EXISTS
FOR (c:Company) ON (c.name);

CREATE INDEX title_postcode_idx IF NOT EXISTS
FOR (t:Title) ON (t.postcode);

CREATE INDEX person_name_normalised_idx IF NOT EXISTS
FOR (p:Person) ON (p.name_normalised);

CREATE INDEX address_postcode_idx IF NOT EXISTS
FOR (a:Address) ON (a.postcode);