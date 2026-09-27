# code/business_entity_resolution/src/run_cleaning.py
"""
Business Entity Resolution -- Data Cleaning Driver
===================================================
Processes each source file independently (load -> normalize -> save -> free RAM)
so files appear in dataset/clean/ one by one with visible progress.

Run from the project root:
    python -u code/business_entity_resolution/src/run_cleaning.py

Output: dataset/clean/  +  data_profile_report.md
"""

import re
import sys
import random
import time
from pathlib import Path
from io import StringIO

import pandas as pd

# Make src importable when run directly
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from cleaning import normalize_dataframe

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT      = Path(__file__).resolve().parents[3]   # ML Project root
TRAIN_DIR = ROOT / "train"
TEST_DIR  = ROOT / "test"
CLEAN_DIR = ROOT / "dataset" / "clean"
CLEAN_DIR.mkdir(parents=True, exist_ok=True)

print(f"Project root : {ROOT}", flush=True)
print(f"Train data   : {TRAIN_DIR}", flush=True)
print(f"Test data    : {TEST_DIR}", flush=True)
print(f"Clean output : {CLEAN_DIR}", flush=True)
print(flush=True)

# ---------------------------------------------------------------------------
# Logging to both stdout and a string buffer (for the report)
# ---------------------------------------------------------------------------
_LOG = StringIO()

def log(msg=""):
    print(msg, flush=True)
    _LOG.write(msg + "\n")


# ============================================================================
# Helper: process ONE file  (load -> normalize -> save -> return stats)
# ============================================================================
def process_file(in_path: Path, out_name: str, source_tag: str) -> dict:
    """Load, normalize, and save a single source TSV. Returns a stats dict."""
    log(f"\n--- {source_tag} : {in_path.name} ---")
    t0 = time.time()

    # Load
    log(f"  Loading ...", )
    df = pd.read_csv(in_path, sep="\t", dtype=str,
                     encoding="utf-8", encoding_errors="replace")
    df.columns = [c.strip() for c in df.columns]
    log(f"  Loaded  {len(df):,} rows x {df.shape[1]} cols  ({time.time()-t0:.1f}s)")

    # Validate prefix
    expected = {"S1": "S1-", "S2": "S2-", "S3": "S3-"}.get(source_tag[:2], "")
    bad_prefix = 0
    if expected:
        bad_prefix = (~df["entity_id"].str.startswith(expected, na=False)).sum()

    nulls = df.isnull().sum().to_dict()
    dups  = df.duplicated(subset=["entity_id"]).sum()
    log(f"  Nulls   : {nulls}")
    log(f"  Dup IDs : {dups}   Bad prefix: {bad_prefix}")

    # Countries
    log(f"  Countries: {df['country'].value_counts(dropna=False).to_dict()}")

    # Normalize
    log(f"  Normalizing ...")
    t1 = time.time()
    df_clean = normalize_dataframe(df, source_tag)
    log(f"  Normalized in {time.time()-t1:.1f}s")

    # Garbled / empty stats
    garbled    = int(df_clean["is_garbled_name"].sum())
    empty_norm = int((df_clean["normalized_name"].str.strip() == "").sum())
    empty_core = int((df_clean["stripped_core_name"].str.strip() == "").sum())
    log(f"  Garbled names: {garbled}   Empty normalized: {empty_norm}   Empty core: {empty_core}")

    # Save
    out_path = CLEAN_DIR / out_name
    log(f"  Saving -> {out_path.name} ...")
    df_clean.to_csv(out_path, sep="\t", index=False)
    total = time.time() - t0
    log(f"  Done in {total:.1f}s total.  Saved {len(df_clean):,} rows x {df_clean.shape[1]} cols.")

    return {
        "file": out_name, "rows": len(df_clean), "cols": df_clean.shape[1],
        "nulls": nulls, "dups": dups, "bad_prefix": bad_prefix,
        "garbled": garbled, "empty_norm": empty_norm, "empty_core": empty_core,
        "seconds": round(total, 1),
    }


# ============================================================================
# STEP 1+2+3 combined — process each file independently
# ============================================================================
log("=" * 65)
log("STEPS 1-3: LOAD, VALIDATE, NORMALIZE, SAVE (one file at a time)")
log("=" * 65)

stats_all = []

# --- Train files ---
stats_all.append(process_file(TRAIN_DIR / "train_source1.tsv", "train_source1_clean.tsv", "S1"))
stats_all.append(process_file(TRAIN_DIR / "train_source2.tsv", "train_source2_clean.tsv", "S2"))
stats_all.append(process_file(TRAIN_DIR / "train_source3.tsv", "train_source3_clean.tsv", "S3"))

# --- Ground truth (copy as-is, no normalization needed) ---
log(f"\n--- GT : train_ground_truth.tsv ---")
gt = pd.read_csv(TRAIN_DIR / "train_ground_truth.tsv", sep="\t", dtype=str,
                 encoding="utf-8", encoding_errors="replace")
gt.columns = [c.strip() for c in gt.columns]
log(f"  Loaded  {len(gt):,} rows")
gt.to_csv(CLEAN_DIR / "train_ground_truth_clean.tsv", sep="\t", index=False)
log(f"  Saved -> train_ground_truth_clean.tsv")

# --- Test files ---
stats_all.append(process_file(TEST_DIR / "test_source1.tsv", "test_source1_clean.tsv", "S1"))
stats_all.append(process_file(TEST_DIR / "test_source2.tsv", "test_source2_clean.tsv", "S2"))
stats_all.append(process_file(TEST_DIR / "test_source3.tsv", "test_source3_clean.tsv", "S3"))


# ============================================================================
# STEP 2 — Country audit (using saved clean files)
# ============================================================================
log("\n" + "=" * 65)
log("STEP 2: COUNTRY AUDIT")
log("=" * 65)

train_countries = set()
test_countries  = set()

for stat in stats_all:
    fname = stat["file"]
    df_c  = pd.read_csv(CLEAN_DIR / fname, sep="\t", dtype=str,
                        usecols=["country"], encoding_errors="replace")
    counts = df_c["country"].value_counts(dropna=False)
    log(f"\n  {fname}:")
    for val, cnt in counts.items():
        log(f"    {str(val)!r:30s} -> {cnt:>8,}")
    if "train" in fname:
        train_countries |= set(df_c["country"].dropna().unique())
    else:
        test_countries  |= set(df_c["country"].dropna().unique())

test_only = test_countries - train_countries
log(f"\n  Countries in TEST only (unseen in train): {test_only}")


# ============================================================================
# STEP 3 — Match-count distribution (ground truth)
# ============================================================================
log("\n" + "=" * 65)
log("STEP 3b: GROUND TRUTH MATCH-COUNT DISTRIBUTION")
log("=" * 65)

gt2 = pd.read_csv(CLEAN_DIR / "train_ground_truth_clean.tsv", sep="\t", dtype=str)
s1_clean = pd.read_csv(CLEAN_DIR / "train_source1_clean.tsv", sep="\t", dtype=str,
                       usecols=["entity_id"])

gt2["n_matches"] = gt2["matched_entity_ids"].apply(
    lambda x: len([m for m in str(x).split(",") if m.strip()]) if pd.notna(x) else 0
)
dist = gt2["n_matches"].value_counts().sort_index()
log("  n_matches | count")
for n, c in dist.items():
    log(f"     {n:>8} | {c:>10,}")

s1_in_gt   = set(gt2["source1_entity_id"])
singletons = set(s1_clean["entity_id"]) - s1_in_gt
log(f"\n  S1 with 0 matches (singletons): {len(singletons):,}")
log(f"  S1 with >=1 match             : {len(s1_in_gt):,}")
log(f"  Total S1                      : {len(s1_clean):,}")


# ============================================================================
# STEP 4 — Sanity check: 10 matched pairs before/after
# ============================================================================
log("\n" + "=" * 65)
log("STEP 4: NORMALIZATION SANITY CHECK (10 matched pairs)")
log("=" * 65)

random.seed(42)
s1_idx = pd.read_csv(CLEAN_DIR / "train_source1_clean.tsv", sep="\t", dtype=str).set_index("entity_id")
s2_idx = pd.read_csv(CLEAN_DIR / "train_source2_clean.tsv", sep="\t", dtype=str).set_index("entity_id")
s3_idx = pd.read_csv(CLEAN_DIR / "train_source3_clean.tsv", sep="\t", dtype=str).set_index("entity_id")

gt_sample = gt2[gt2["matched_entity_ids"].notna()].sample(10, random_state=42)
for i, (_, gt_row) in enumerate(gt_sample.iterrows(), 1):
    s1_id = gt_row["source1_entity_id"]
    if s1_id not in s1_idx.index:
        continue
    s1r = s1_idx.loc[s1_id]
    mid = str(gt_row["matched_entity_ids"]).split(",")[0].strip()
    if mid.startswith("S2-") and mid in s2_idx.index:
        tgt = s2_idx.loc[mid]
    elif mid.startswith("S3-") and mid in s3_idx.index:
        tgt = s3_idx.loc[mid]
    else:
        continue
    log(f"\n  [{i}] S1={s1_id} -> matched={mid}")
    log(f"       RAW  name S1 : {s1r.get('business_name','')!r}")
    log(f"       NORM name S1 : {s1r.get('normalized_name','')!r}")
    log(f"       CORE name S1 : {s1r.get('stripped_core_name','')!r}")
    log(f"       RAW  name TGT: {tgt.get('business_name','')!r}")
    log(f"       NORM name TGT: {tgt.get('normalized_name','')!r}")
    log(f"       CORE name TGT: {tgt.get('stripped_core_name','')!r}")
    log(f"       RAW  addr S1 : {s1r.get('business_address','')!r}")
    log(f"       NORM addr S1 : {s1r.get('normalized_address','')!r}")
    log(f"       RAW  addr TGT: {tgt.get('business_address','')!r}")
    log(f"       NORM addr TGT: {tgt.get('normalized_address','')!r}")


# ============================================================================
# STEP 5 — Summary table + write report
# ============================================================================
log("\n" + "=" * 65)
log("STEP 5: SUMMARY")
log("=" * 65)
log(f"\n  {'File':<38} {'Rows':>10} {'Cols':>5} {'Secs':>6} {'Garbled':>8} {'EmptyNorm':>10}")
log("  " + "-" * 80)
for s in stats_all:
    log(f"  {s['file']:<38} {s['rows']:>10,} {s['cols']:>5} {s['seconds']:>6.1f} {s['garbled']:>8,} {s['empty_norm']:>10,}")

log(f"\n  All clean files saved to: {CLEAN_DIR}")

# Write report
report_md = ROOT / "data_profile_report.md"
with open(report_md, "w", encoding="utf-8") as f:
    f.write("# Data Profile Report -- Business Entity Resolution\n\n")
    f.write("```\n")
    f.write(_LOG.getvalue())
    f.write("\n```\n")

log(f"\n  Report saved: {report_md}")
log("\nDONE.")
