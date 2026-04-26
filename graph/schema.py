from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Node definitions
# ---------------------------------------------------------------------------

@dataclass
class TitleNode:
    title_number: str
    tenure: str
    proprietor_name: str
    address: str
    postcode: str
    price_paid: Optional[float] = None
    date_registered: Optional[str] = None

    LABEL = "Title"


@dataclass
class CompanyNode:
    company_number: str
    company_name: str
    company_status: str
    company_type: str
    postcode: Optional[str] = None

    LABEL = "Company"


@dataclass
class PersonNode:
    name: str
    nationality: Optional[str] = None
    country_of_residence: Optional[str] = None

    LABEL = "Person"


@dataclass
class OfficerNode(PersonNode):
    """Person in an officer role — resolved to Person node in graph."""
    role: str = ""
    company_number: str = ""


@dataclass
class PSCNode(PersonNode):
    """Person with significant control — resolved to Person node in graph."""
    nature_of_control: list[str] = field(default_factory=list)
    company_number: str = ""


@dataclass
class CharityNode:
    charity_number: str
    charity_name: str
    status: str
    postcode: Optional[str] = None

    LABEL = "Charity"


# ---------------------------------------------------------------------------
# Relationship definitions
# ---------------------------------------------------------------------------

@dataclass
class OwnsRel:
    """(Company)-[:OWNS]->(Title)"""
    company_number: str
    title_number: str

    TYPE = "OWNS"


@dataclass
class OfficerOfRel:
    """(Person)-[:OFFICER_OF]->(Company)"""
    person_name: str
    company_number: str
    role: str
    appointed_on: Optional[str] = None
    resigned_on: Optional[str] = None

    TYPE = "OFFICER_OF"


@dataclass
class PSCOfRel:
    """(Person)-[:PSC_OF]->(Company)"""
    person_name: str
    company_number: str
    nature_of_control: list[str] = field(default_factory=list)
    notified_on: Optional[str] = None
    ceased_on: Optional[str] = None

    TYPE = "PSC_OF"


@dataclass
class TrusteeIsRel:
    """(Charity)-[:TRUSTEE_IS]->(Person)"""
    charity_number: str
    person_name: str

    TYPE = "TRUSTEE_IS"


@dataclass
class LinkedToRel:
    """(Company)-[:LINKED_TO]->(Company)  — group structures / common control"""
    from_company_number: str
    to_company_number: str
    link_type: str = "group"

    TYPE = "LINKED_TO"
