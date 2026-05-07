"""
Data normalization utilities for corporate ownership detection.
Provides deterministic hashing and standardization for entity matching.
"""

import hashlib
import re
import unicodedata


def normalise_name(name: str) -> str:
    """
    Normalize company/person names for consistent matching.
    
    Steps:
    - Lowercase
    - Strip whitespace  
    - Normalize unicode hyphens (per commit e0f36cb)
    - Collapse multiple spaces
    - Strip common company suffixes
    """
    if not name:
        return ""
    
    # Lowercase and strip
    normalized = name.lower().strip()
    
    # Normalize unicode hyphens to ASCII hyphen
    normalized = unicodedata.normalize('NFKC', normalized)
    normalized = re.sub(r'[\u2010-\u2015\u2212\uFE58\uFE63\uFF0D]', '-', normalized)
    
    # Collapse multiple spaces
    normalized = re.sub(r'\s+', ' ', normalized)
    
    # Strip common company suffixes for matching
    suffixes = [
        r'\bltd\.?$', r'\blimited$', r'\bplc\.?$', r'\bllp\.?$', 
        r'\bllc\.?$', r'\binc\.?$', r'\bcorp\.?$', r'\b&\s*co\.?$'
    ]
    for suffix in suffixes:
        normalized = re.sub(suffix, '', normalized, flags=re.IGNORECASE).strip()
    
    return normalized


def normalise_postcode(postcode: str) -> str:
    """
    Normalize UK postcodes to standard format.
    
    Example: 'sw1a 1aa' -> 'SW1A 1AA'
    """
    if not postcode:
        return ""
    
    # Uppercase and strip
    normalized = postcode.upper().strip()
    
    # Remove all spaces
    normalized = re.sub(r'\s+', '', normalized)
    
    # Insert space before last 3 characters (UK postcode format)
    if len(normalized) >= 5:
        normalized = f"{normalized[:-3]} {normalized[-3:]}"
    
    return normalized


def person_id(name: str, dob_year_month: str, country_of_residence: str) -> str:
    """
    Generate deterministic hash for Person deduplication.
    
    Args:
        name: Person's name
        dob_year_month: Format "YYYY-MM" (e.g. "1975-03")  
        country_of_residence: Country name/code
        
    Returns:
        SHA256 hex digest (64 chars)
    """
    normalized_name = normalise_name(name)
    dob = dob_year_month or ""
    country = (country_of_residence or "").lower().strip()
    
    composite = f"{normalized_name}|{dob}|{country}"
    return hashlib.sha256(composite.encode('utf-8')).hexdigest()


def address_id(postcode: str, premises: str) -> str:
    """
    Generate deterministic hash for Address deduplication.
    
    Args:
        postcode: UK postcode
        premises: Building name/number and street
        
    Returns:
        SHA256 hex digest (64 chars)
    """
    normalized_postcode = normalise_postcode(postcode)
    normalized_premises = (premises or "").lower().strip()
    
    composite = f"{normalized_postcode}|{normalized_premises}"
    return hashlib.sha256(composite.encode('utf-8')).hexdigest()