# verify_cleaning.py
"""
Quick terminal verification of cleaned TSV files.
Run from the project root:
    python verify_cleaning.py

Checks performed:
  1. All 7 clean files exist with correct row/column counts
  2. No new columns are missing
  3. Null rates in new columns
  4. Sample before/after rows for visual inspection
  5. Garbled name flag counts
  6. Empty normalized name/address counts
  7. Suffix expansion spot-check
  8. Phonetic key spot-check
"""

import sys
from pathlib import Path
import pandas as pd

CLEAN_DIR = Path("dataset/clean")
REQUIRED_COLS = [
    "entity_id", "business_name", "business_address", "country",
    "is_garbled_name", "normalized_name", "expanded_name",
    "stripped_core_name", "metaphone_key", "soundex_key",
    "normalized_address", "numeric_tokens", "address_text_core",
]

CLEAN_FILES = [
    "train_source1_clean.tsv",
    "train_source2_clean.tsv",
    "train_source3_clean.tsv",
    "test_source1_clean.tsv",
    "test_source2_clean.tsv",
    "test_source3_clean.tsv",
]

SEP = "=" * 65

def banner(msg):
    print(f"\n{SEP}")
    print(f"  {msg}")
    print(SEP)

def ok(msg):   print(f"  [OK]   {msg}")
def warn(msg): print(f"  [WARN] {msg}")
def err(msg):  print(f"  [ERR]  {msg}")

# ─── 1. File existence & shape ───────────────────────────────────────────────
banner("CHECK 1 — File existence & shape")
frames = {}
all_ok = True
for fname in CLEAN_FILES:
    path = CLEAN_DIR / fname
    if not path.exists():
        err(f"MISSING: {fname}")
        all_ok = False
        continue
    df = pd.read_csv(path, sep="\t", dtype=str, nrows=None,
                     encoding="utf-8", encoding_errors="replace")
    frames[fname] = df
    ok(f"{fname:40s}  rows={len(df):>9,}  cols={df.shape[1]}")

if not all_ok:
    print("\n  Pipeline output is incomplete — run_cleaning.py may still be running.")
    sys.exit(1)

# ─── 2. Required columns present ─────────────────────────────────────────────
banner("CHECK 2 — Required columns present in each file")
for fname, df in frames.items():
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        err(f"{fname}: missing columns -> {missing}")
    else:
        ok(f"{fname}: all {len(REQUIRED_COLS)} required columns present")

# ─── 3. Null rates in new columns ─────────────────────────────────────────────
banner("CHECK 3 — Null rates in new (derived) columns")
NEW_COLS = REQUIRED_COLS[4:]   # everything after original 4
for fname, df in frames.items():
    print(f"\n  [{fname}]")
    for col in NEW_COLS:
        if col not in df.columns:
            continue
        null_n  = df[col].isna().sum()
        empty_n = (df[col].fillna("").str.strip() == "").sum()
        rate    = null_n / len(df) * 100
        status  = warn if rate > 5 else ok
        status(f"    {col:25s}  nulls={null_n:>7,} ({rate:5.1f}%)  "
               f"empty_str={empty_n:>7,}")

# ─── 4. Garbled name counts ────────────────────────────────────────────────
banner("CHECK 4 — Garbled business_name counts")
for fname, df in frames.items():
    if "is_garbled_name" not in df.columns:
        continue
    garbled = (df["is_garbled_name"].str.lower() == "true").sum()
    pct = garbled / len(df) * 100
    fn = warn if pct > 1 else ok
    fn(f"{fname:40s}  garbled={garbled:>7,}  ({pct:.2f}%)")

# ─── 5. Empty normalized_name ─────────────────────────────────────────────
banner("CHECK 5 — Empty normalized_name (after cleaning)")
for fname, df in frames.items():
    if "normalized_name" not in df.columns:
        continue
    empty = (df["normalized_name"].fillna("").str.strip() == "").sum()
    pct = empty / len(df) * 100
    fn = warn if pct > 2 else ok
    fn(f"{fname:40s}  empty_normalized_name={empty:>7,}  ({pct:.2f}%)")

# ─── 6. Empty normalized_address (where raw address was non-null) ──────────
banner("CHECK 6 — Addresses lost after normalization")
for fname, df in frames.items():
    if "normalized_address" not in df.columns:
        continue
    has_raw   = df["business_address"].fillna("").str.strip() != ""
    lost_addr = (has_raw & (df["normalized_address"].fillna("").str.strip() == "")).sum()
    fn = warn if lost_addr > 0 else ok
    fn(f"{fname:40s}  addresses_lost={lost_addr:>6,}")

# ─── 7. Before/After sample — 5 random rows from train_source1 ─────────────
banner("CHECK 7 — Before/After sample (train_source1, 5 rows)")
df1 = frames.get("train_source1_clean.tsv")
if df1 is not None:
    sample = df1.sample(5, random_state=7)
    for _, row in sample.iterrows():
        print()
        print(f"  entity_id      : {row['entity_id']}")
        print(f"  RAW   name     : {row['business_name']!r}")
        print(f"  NORM  name     : {row['normalized_name']!r}")
        print(f"  EXPANDED name  : {row['expanded_name']!r}")
        print(f"  CORE  name     : {row['stripped_core_name']!r}")
        print(f"  METAPHONE key  : {row['metaphone_key']!r}")
        print(f"  RAW   address  : {row['business_address']!r}")
        print(f"  NORM  address  : {row['normalized_address']!r}")
        print(f"  NUMERIC tokens : {row['numeric_tokens']!r}")
        print(f"  ADDR  core     : {row['address_text_core']!r}")

# ─── 8. Suffix expansion spot-check ────────────────────────────────────────
banner("CHECK 8 — Suffix expansion spot-check (names containing corp/pvt/ltd/inc)")
df1 = frames.get("train_source1_clean.tsv")
if df1 is not None:
    mask = df1["business_name"].fillna("").str.lower().str.contains(
        r"\b(corp|pvt|ltd|inc|llc|assoc)\b", regex=True, na=False
    )
    hits = df1[mask][["business_name", "expanded_name", "stripped_core_name"]].head(8)
    if hits.empty:
        warn("No abbreviated-suffix names found in sample — check source data")
    else:
        print(hits.to_string(index=False))

# ─── 9. Phonetic key spot-check ─────────────────────────────────────────────
banner("CHECK 9 — Phonetic key spot-check (India records from train_source3)")
df3 = frames.get("train_source3_clean.tsv")
if df3 is not None:
    india = df3[df3["country"].fillna("").str.strip().str.lower().isin(
        ["india", "in"]
    )].head(5)
    if india.empty:
        warn("No India records found")
    else:
        print(india[["business_name", "stripped_core_name",
                      "metaphone_key", "soundex_key"]].to_string(index=False))

# ─── 10. Duplicate entity_id check in clean files ──────────────────────────
banner("CHECK 10 — Duplicate entity_ids in clean files")
for fname, df in frames.items():
    dups = df.duplicated(subset=["entity_id"]).sum()
    fn = err if dups > 0 else ok
    fn(f"{fname:40s}  dup_entity_ids={dups}")

print(f"\n{SEP}")
print("  Verification complete.")
print(SEP)
