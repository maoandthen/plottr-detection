from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Node definitions
# ---------------------------------------------------------------------------

@dataclass
class TitleNode:
    title_number: str
    tenure: str
    address_id: Optional[str]  # FK ref to AddressNode
    geom: Optional[str]
    price_paid: Optional[float]
    date_registered: Optional[str]
    source: str  # ccod / ocod

    LABEL = "Title"


@dataclass
class CompanyNode:
    company_number: str
    company_name: str
    company_status: str
    company_type: str
    incorporated_on: Optional[str]
    sic_codes: list[str] = field(default_factory=list)

    LABEL = "Company"


@dataclass
class PersonNode:
    person_id: str  # deterministic UUID (see entity_resolution.py)
    full_name: str
    date_of_birth: Optional[str]  # YYYY-MM or YYYY-MM-DD
    nationality: Optional[str]
    country_of_residence: Optional[str]

    LABEL = "Person"


@dataclass
class CharityNode:
    charity_number: str
    charity_name: str
    charity_type: Optional[str]
    registration_date: Optional[str]
    deregistration_date: Optional[str]

    LABEL = "Charity"


@dataclass
class AddressNode:
    uprn: Optional[str]  # nullable
    address_string: str  # normalised
    postcode: str
    geom: Optional[str]  # Point SRID 4326

    LABEL = "Address"


# ---------------------------------------------------------------------------
# Relationship definitions
# ---------------------------------------------------------------------------

@dataclass
class OwnedByRel:
    """(Title)-[:OWNED_BY]->(Company | Person | Charity)"""
    title_number: str
    owner_id: str  # company_number / person_id / charity_number
    proprietor_category: str
    date_from: Optional[str]

    TYPE = "OWNED_BY"


@dataclass
class OfficerOfRel:
    """(Person)-[:OFFICER_OF]->(Company)"""
    person_id: str
    company_number: str
    role: str
    appointed_on: Optional[str]
    resigned_on: Optional[str]

    TYPE = "OFFICER_OF"


@dataclass
class PSCOfRel:
    """(Person | Company)-[:PSC_OF]->(Company)"""
    subject_id: str  # person_id or company_number
    company_number: str
    nature_of_control: list[str] = field(default_factory=list)
    notified_on: Optional[str] = None
    ceased_on: Optional[str] = None

    TYPE = "PSC_OF"


@dataclass
class TrusteeOfRel:
    """(Person)-[:TRUSTEE_OF]->(Charity)"""
    person_id: str
    charity_number: str
    appointed_on: Optional[str]
    ended_on: Optional[str]

    TYPE = "TRUSTEE_OF"


@dataclass
class RegisteredAtRel:
    """(Company | Person | Charity | Title)-[:REGISTERED_AT]->(Address)"""
    subject_id: str
    address_id: str
    address_type: str  # registered / correspondence / service
    valid_from: Optional[str]
    valid_to: Optional[str]

    TYPE = "REGISTERED_AT"
