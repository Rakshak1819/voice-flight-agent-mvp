from __future__ import annotations

import re

# Canonical labels balance readability while preserving airport precision.
_CODE_TO_LABEL = {
    "ATL": "Atlanta (ATL)",
    "BOS": "Boston (BOS)",
    "CLT": "Charlotte (CLT)",
    "DAL": "Dallas Love Field (DAL)",
    "DCA": "Washington National (DCA)",
    "DEN": "Denver (DEN)",
    "DFW": "Dallas/Fort Worth (DFW)",
    "DTW": "Detroit (DTW)",
    "EWR": "Newark (EWR)",
    "IAD": "Washington Dulles (IAD)",
    "IAH": "Houston (IAH)",
    "JFK": "New York JFK (JFK)",
    "LAS": "Las Vegas (LAS)",
    "LAX": "Los Angeles (LAX)",
    "LGA": "New York LaGuardia (LGA)",
    "MCO": "Orlando (MCO)",
    "MIA": "Miami (MIA)",
    "MSP": "Minneapolis (MSP)",
    "ORD": "Chicago O'Hare (ORD)",
    "PDX": "Portland (PDX)",
    "PHX": "Phoenix (PHX)",
    "SAN": "San Diego (SAN)",
    "SEA": "Seattle-Tacoma (SEA)",
    "SFO": "San Francisco (SFO)",
}

_ALIASES = {
    "atl": "ATL",
    "bos": "BOS",
    "clt": "CLT",
    "dal": "DAL",
    "dallas love field": "DAL",
    "dca": "DCA",
    "den": "DEN",
    "dtw": "DTW",
    "dfw": "DFW",
    "dallas fort worth": "DFW",
    "dallas fort worth international": "DFW",
    "dallas fort worth intl": "DFW",
    "ewr": "EWR",
    "iad": "IAD",
    "dulles": "IAD",
    "washington dulles": "IAD",
    "iah": "IAH",
    "jfk": "JFK",
    "john f kennedy": "JFK",
    "john f kennedy international": "JFK",
    "las": "LAS",
    "lax": "LAX",
    "lga": "LGA",
    "laguardia": "LGA",
    "new york laguardia": "LGA",
    "mco": "MCO",
    "mia": "MIA",
    "msp": "MSP",
    "ord": "ORD",
    "ohare": "ORD",
    "o hare": "ORD",
    "chicago ohare": "ORD",
    "pdx": "PDX",
    "phx": "PHX",
    "san": "SAN",
    "sea": "SEA",
    "seattle tacoma": "SEA",
    "seattle tacoma international": "SEA",
    "sfo": "SFO",
}


def normalize_location_text(value: str) -> str:
    raw = value.strip(" .,")
    if not raw:
        return ""

    for label in _CODE_TO_LABEL.values():
        if raw.lower() == label.lower():
            return label

    trailing_code = re.search(r"\(([A-Za-z]{3})\)\s*$", raw)
    if trailing_code:
        code = trailing_code.group(1).upper()
        if code in _CODE_TO_LABEL:
            return _CODE_TO_LABEL[code]
        prefix = raw[: trailing_code.start()].strip(" ,-")
        if prefix:
            return f"{_title_case_place(prefix)} ({code})"
        return code

    # Remove common filler words while preserving code/name meaning.
    key = raw.lower()
    key = re.sub(r"\b(airport|international|intl|airfield|terminal)\b", " ", key)
    key = re.sub(r"[^a-z0-9 ]+", " ", key)
    key = re.sub(r"\s+", " ", key).strip()

    if key in _ALIASES:
        code = _ALIASES[key]
        return _CODE_TO_LABEL.get(code, code)

    maybe_code = re.fullmatch(r"[A-Za-z]{3}", raw.strip())
    if maybe_code:
        code = raw.strip().upper()
        return _CODE_TO_LABEL.get(code, code)

    return _title_case_place(raw)


def _title_case_place(value: str) -> str:
    words: list[str] = []
    for token in value.strip().split():
        paren_code = re.fullmatch(r"\(([A-Za-z]{2,4})\)", token)
        if paren_code:
            words.append(f"({paren_code.group(1).upper()})")
            continue

        if "/" in token:
            parts = token.split("/")
            titled_parts: list[str] = []
            for part in parts:
                if part.isupper() and len(part) <= 4:
                    titled_parts.append(part)
                else:
                    titled_parts.append(part.capitalize())
            words.append("/".join(titled_parts))
            continue

        if token.isupper() and len(token) <= 4:
            words.append(token)
        else:
            words.append(token.capitalize())
    return " ".join(words)
