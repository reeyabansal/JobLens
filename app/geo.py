"""Infer a country from a free-text location string, for location filtering.

Deliberately small and predictable: explicit country names (word-boundary),
US state codes / Canadian provinces, and a "remote" signal. Returns a canonical
country name, the string "Remote", or None when it can't tell.
"""
from __future__ import annotations

import re

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}
CA_PROVINCES = {"ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE"}

# full country names / common aliases -> canonical. Word-boundary matched.
COUNTRY_KEYWORDS = {
    "united states": "United States", "usa": "United States", "u.s.a": "United States",
    "u.s.": "United States", "america": "United States",
    "canada": "Canada", "united kingdom": "United Kingdom", "u.k.": "United Kingdom",
    "uk": "United Kingdom", "england": "United Kingdom", "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "ireland": "Ireland", "germany": "Germany", "france": "France", "spain": "Spain",
    "portugal": "Portugal", "italy": "Italy", "netherlands": "Netherlands",
    "poland": "Poland", "romania": "Romania", "ukraine": "Ukraine", "sweden": "Sweden",
    "switzerland": "Switzerland", "austria": "Austria", "belgium": "Belgium",
    "india": "India", "pakistan": "Pakistan", "bangladesh": "Bangladesh",
    "vietnam": "Vietnam", "philippines": "Philippines", "indonesia": "Indonesia",
    "malaysia": "Malaysia", "singapore": "Singapore", "thailand": "Thailand",
    "china": "China", "hong kong": "Hong Kong", "taiwan": "Taiwan", "japan": "Japan",
    "south korea": "South Korea", "korea": "South Korea",
    "australia": "Australia", "new zealand": "New Zealand",
    "brazil": "Brazil", "mexico": "Mexico", "argentina": "Argentina", "chile": "Chile",
    "colombia": "Colombia", "nigeria": "Nigeria", "kenya": "Kenya", "egypt": "Egypt",
    "south africa": "South Africa", "israel": "Israel", "turkey": "Turkey",
    "united arab emirates": "United Arab Emirates", "uae": "United Arab Emirates",
    "saudi arabia": "Saudi Arabia",
}


def infer_country(location: str) -> str | None:
    if not location:
        return None
    text = location.strip()
    low = text.lower()

    # explicit country names first (word boundaries so "us" never matches "Austin")
    for kw, country in COUNTRY_KEYWORDS.items():
        if re.search(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])", low):
            return country

    # "City, ST" US state / Canadian province codes
    codes = re.findall(r",\s*([A-Za-z]{2})(?:\s|,|$|\))", text)
    codes = {c.upper() for c in codes}
    if codes & US_STATES:
        return "United States"
    if codes & CA_PROVINCES:
        return "Canada"

    # bare "Remote" with no country
    if "remote" in low:
        return "Remote"
    return None


def is_remote(location: str, remote_flag: bool = False) -> bool:
    return bool(remote_flag) or "remote" in (location or "").lower()
