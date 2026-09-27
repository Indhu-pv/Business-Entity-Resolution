# src/cleaning.py
"""
Business Entity Resolution -- Data Cleaning Module
===================================================
Provides reusable, country-agnostic text normalization functions for
business names and addresses. Processes tens of millions of rows efficiently.

Key design:
- Basic text ops (lowercase, punctuation strip) use pandas vectorised str methods
- Legal suffix expansion and address abbreviation expansion use direct Python
  list comprehensions over pre-split token lists -- faster than pandas groupby
  or sequential str.replace() calls for this workload
- Phonetic keys use jellyfish (no array API available)
- All original columns preserved; only new columns added

Usage:
    from src.cleaning import normalize_dataframe
    df_clean = normalize_dataframe(df, source_tag="S1")
"""

import re
from typing import Optional

import pandas as pd
import jellyfish

# ---------------------------------------------------------------------------
# Legal-suffix synonym map  (variant token -> canonical expanded form)
# ---------------------------------------------------------------------------
SUFFIX_VARIANT_TO_CANONICAL: dict = {
    "corp": "corporation", "corporations": "corporation",
    "inc": "incorporated", "inco": "incorporated",
    "ltd": "limited", "lmt": "limited", "lmtd": "limited",
    "pvt": "private", "priv": "private",
    "co": "company", "coy": "company",
    "assoc": "associates", "assocs": "associates", "associate": "associates",
    "enterprise": "enterprises", "ent": "enterprises", "ents": "enterprises",
    "svc": "services", "svcs": "services", "service": "services",
    "soln": "solutions", "solns": "solutions", "solution": "solutions",
    "intl": "international",
    "tech": "technologies", "techs": "technologies", "technology": "technologies",
    "ind": "industries", "inds": "industries", "industry": "industries",
    "bros": "brothers", "bro": "brothers",
    "grp": "group",
    "mgmt": "management",
    "sys": "systems",
    "consult": "consulting", "consultants": "consulting", "consultant": "consulting",
    "trdg": "trading",
    "holding": "holdings", "hldg": "holdings", "hldgs": "holdings",
}

# Canonical suffix tokens (for tail-stripping after expansion)
LEGAL_SUFFIX_CANONICAL: dict = {
    "corporation": [], "incorporated": [], "limited": [], "private": [],
    "company": [], "llc": [], "llp": [], "lp": [], "plc": [], "pllc": [],
    "associates": [], "enterprises": [], "services": [], "solutions": [],
    "international": [], "technologies": [], "industries": [], "brothers": [],
    "group": [], "management": [], "systems": [], "consulting": [],
    "trading": [], "holdings": [],
}
_CANONICAL_SET: set = set(LEGAL_SUFFIX_CANONICAL.keys())

# Pre-compile suffix strip regex (matches ONE trailing canonical suffix at end of string)
_SUFFIX_STRIP_RE = re.compile(
    r'\s*\b(' + '|'.join(re.escape(t) for t in sorted(_CANONICAL_SET, key=len, reverse=True)) + r')\s*$'
)

# ---------------------------------------------------------------------------
# Address abbreviation map  (abbreviated -> expanded)
# ---------------------------------------------------------------------------
ADDRESS_ABBR_MAP: dict = {
    "rd": "road", "st": "street", "ave": "avenue",
    "blvd": "boulevard", "dr": "drive", "ln": "lane",
    "ct": "court", "pl": "place", "sq": "square",
    "hwy": "highway", "fwy": "freeway", "expy": "expressway",
    "pkwy": "parkway", "cir": "circle", "trl": "trail",
    "ter": "terrace", "apt": "apartment", "ste": "suite",
    "bldg": "building", "flr": "floor", "rm": "room",
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest",
    "se": "southeast", "sw": "southwest",
    "col": "colony", "sec": "sector",
    "dist": "district", "distric": "district",
    "ph": "phase", "blk": "block", "no": "number",
}

# Numeric token pattern (house numbers, PINs, ZIPs)
_DIGIT_SEQ_RE = re.compile(r"\b\d[\d\-/]*\b")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _expand_name(name: str) -> str:
    """Expand suffix abbreviations in a single normalized name (fast scalar)."""
    if not name:
        return ""
    return " ".join(SUFFIX_VARIANT_TO_CANONICAL.get(t, t) for t in name.split())


def _strip_name(name: str) -> str:
    """Strip trailing canonical suffix tokens from a single expanded name."""
    result = name
    while True:
        new = _SUFFIX_STRIP_RE.sub("", result).strip()
        if new == result:
            break
        result = new
    return result


def _normalize_addr(addr: str) -> str:
    """Normalize and expand abbreviations in a single address string."""
    if not isinstance(addr, str):
        return ""
    text = re.sub(r"[^\w\s,]", " ", addr.lower())
    text = re.sub(r"\s+", " ", text).strip()
    tokens = text.split()
    expanded = []
    for tok in tokens:
        clean = tok.rstrip(",")
        tail = tok[len(clean):]
        expanded.append(ADDRESS_ABBR_MAP.get(clean, clean) + tail)
    return " ".join(expanded)


def _is_garbled(text) -> bool:
    """True if >50% of non-whitespace chars are non-printable (encoding corruption)."""
    if not isinstance(text, str) or not text:
        return False
    non_ws = [c for c in text if not c.isspace()]
    if not non_ws:
        return True
    bad = sum(1 for c in non_ws if not c.isprintable())
    return (bad / len(non_ws)) > 0.5


def _phonetic_key(name: str, algorithm: str = "metaphone") -> str:
    """Per-token phonetic key joined with '-'."""
    if not name:
        return ""
    fn = jellyfish.metaphone if algorithm == "metaphone" else jellyfish.soundex
    parts = []
    for tok in name.split():
        try:
            parts.append(fn(tok))
        except Exception:
            parts.append(tok)
    return "-".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Series-level helpers (used by normalize_dataframe)
# ---------------------------------------------------------------------------

def _names_basic_vec(s: pd.Series) -> pd.Series:
    """Lowercase, & -> and, punctuation strip, whitespace collapse. Vectorised."""
    return (
        s.fillna("")
         .str.lower()
         .str.replace("&", " and ", regex=False)
         .str.replace(r"[^\w\s]", " ", regex=True)
         .str.replace(r"\s+", " ", regex=True)
         .str.strip()
    )


# ---------------------------------------------------------------------------
# Public scalar API (for unit tests and downstream feature engineering)
# ---------------------------------------------------------------------------

def normalize_business_name(name: str) -> str:
    """Normalize a single raw business name string."""
    if not isinstance(name, str):
        return ""
    text = name.lower().replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def expand_legal_suffixes(normalized_name: str) -> str:
    """Expand legal-suffix abbreviations in a single normalized name."""
    return _expand_name(normalized_name)


def strip_legal_suffixes(expanded_name: str) -> str:
    """Strip trailing canonical suffix tokens from a single expanded name."""
    return _strip_name(expanded_name)


def phonetic_key(name: str, algorithm: str = "metaphone") -> str:
    """Compute phonetic key for a single cleaned name string."""
    return _phonetic_key(name, algorithm)


def normalize_address(address: str) -> str:
    """Normalize a single raw address string."""
    return _normalize_addr(address)


def extract_numeric_tokens(address: str) -> str:
    """Extract numeric sequences (house/PIN/ZIP) from an address string."""
    if not isinstance(address, str):
        return ""
    return " ".join(_DIGIT_SEQ_RE.findall(address))


def extract_text_remainder(normalized_address: str) -> str:
    """Return normalized address with all numeric tokens removed."""
    if not isinstance(normalized_address, str):
        return ""
    text = re.sub(_DIGIT_SEQ_RE, " ", normalized_address)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# DataFrame-level normalization -- primary entry point
# ---------------------------------------------------------------------------

def normalize_dataframe(df: pd.DataFrame, source_tag: str = "") -> pd.DataFrame:
    """
    Apply all cleaning steps to a source DataFrame (S1, S2, or S3).

    New columns added (all originals untouched):
      - is_garbled_name      : bool -- True if business_name appears corrupted
      - normalized_name      : lowercase, punctuation-removed name
      - expanded_name        : normalized_name with legal suffix abbreviations
                               expanded (corp -> corporation, pvt -> private, etc.)
      - stripped_core_name   : expanded_name with all trailing legal suffix
                               tokens removed (core business identifier)
      - metaphone_key        : per-token metaphone key of stripped_core_name
      - soundex_key          : per-token soundex key of stripped_core_name
      - normalized_address   : lowercase, abbreviation-expanded address
      - numeric_tokens       : digit sequences extracted from raw address
      - address_text_core    : normalized_address minus numeric tokens

    Parameters
    ----------
    df : pd.DataFrame
        Must have columns: entity_id, business_name, business_address, country
    source_tag : str
        Optional label for progress messages (e.g. 'S1').

    Returns
    -------
    pd.DataFrame
        Copy of df with 9 new columns appended.
    """
    df = df.copy()
    tag = f"[{source_tag}]" if source_tag else ""

    # ---- Name columns ----
    print(f"  {tag} garbled flag ...", flush=True)
    df["is_garbled_name"]    = df["business_name"].map(_is_garbled)

    print(f"  {tag} normalize names ...", flush=True)
    df["normalized_name"]    = _names_basic_vec(df["business_name"])

    print(f"  {tag} expand suffixes ...", flush=True)
    df["expanded_name"]      = df["normalized_name"].map(_expand_name)

    print(f"  {tag} strip suffixes ...", flush=True)
    df["stripped_core_name"] = df["expanded_name"].map(_strip_name)

    print(f"  {tag} metaphone keys ...", flush=True)
    df["metaphone_key"]      = df["stripped_core_name"].map(
        lambda x: _phonetic_key(x, "metaphone")
    )

    print(f"  {tag} soundex keys ...", flush=True)
    df["soundex_key"]        = df["stripped_core_name"].map(
        lambda x: _phonetic_key(x, "soundex")
    )

    # ---- Address columns ----
    print(f"  {tag} normalize addresses ...", flush=True)
    df["normalized_address"] = df["business_address"].map(_normalize_addr)

    print(f"  {tag} numeric tokens ...", flush=True)
    df["numeric_tokens"]     = (
        df["business_address"].fillna("").str.findall(_DIGIT_SEQ_RE).str.join(" ")
    )

    print(f"  {tag} address text core ...", flush=True)
    df["address_text_core"]  = (
        df["normalized_address"]
          .str.replace(_DIGIT_SEQ_RE, " ", regex=True)
          .str.replace(r"\s+", " ", regex=True)
          .str.strip()
    )

    print(f"  {tag} done ({len(df):,} rows).", flush=True)
    return df
