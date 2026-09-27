"""Explicit token-join and key-join blockers for business entity resolution.

The token path contains no vectorizer, sparse-matrix similarity, or dense
pairwise search. Its preflight pass streams records and counts unique word
postings before any large token join is attempted.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

import pandas as pd

WORD_RE = re.compile(r"(?u)\b\w{3,}\b")
BLOCK_COLUMNS = [
    "entity_id", "stripped_core_name", "address_text_core",
    "metaphone_key", "soundex_key", "country",
]
CATEGORY_COLUMNS = {column: "category" for column in BLOCK_COLUMNS}


def tokenize_record(name: object, address: object) -> set[str]:
    """Distinct word tokens (length >= 3) from normalized name + address core."""
    text = f"{name or ''} {address or ''}".lower()
    return set(WORD_RE.findall(text))


def token_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Explode one in-memory frame to distinct (entity_id, token) rows."""
    entity_ids: list[str] = []
    tokens: list[str] = []
    for entity_id, name, address in zip(
        frame["entity_id"].astype(str),
        frame["stripped_core_name"].astype(str),
        frame["address_text_core"].astype(str),
    ):
        for token in tokenize_record(name, address):
            entity_ids.append(entity_id)
            tokens.append(token)
    return pd.DataFrame({"entity_id": entity_ids, "token": tokens})


def exact_token_frequencies(path, *, chunk_rows: int = 50_000) -> tuple[int, Counter[str], int]:
    """Stream a source and count exact distinct-record token document frequencies."""
    postings: Counter[str] = Counter()
    row_count = 0
    chunks = 0
    for frame in pd.read_csv(
        path, sep="\t", usecols=["stripped_core_name", "address_text_core"],
        dtype={"stripped_core_name": "category", "address_text_core": "category"},
        keep_default_na=False, encoding="utf-8", encoding_errors="replace",
        chunksize=chunk_rows,
    ):
        chunks += 1
        for name, address in zip(frame["stripped_core_name"], frame["address_text_core"]):
            postings.update(tokenize_record(name, address))
            row_count += 1
        if chunks % 10 == 0:
            print(f"[preflight tokens] {path.name}: rows={row_count:,}, chunks={chunks:,}, "
                  f"distinct_tokens={len(postings):,}", flush=True)
        del frame
    return row_count, postings, chunks


def token_table(frame: pd.DataFrame, *, max_df: float = 0.02) -> tuple[pd.DataFrame, pd.Series, dict]:
    """Build a long token table, compute one value_counts DF, and filter common keys."""
    exploded = token_rows(frame)
    if exploded.empty:
        return exploded, pd.Series(dtype="int64"), {"rows_before": 0, "dropped_tokens": 0}
    # Explicit one-pass document frequency from the long token table.
    document_frequency = exploded["token"].value_counts(sort=False)
    threshold = max(1, int(len(frame) * max_df))
    common = document_frequency[document_frequency > threshold]
    if not common.empty:
        exploded = exploded[~exploded["token"].isin(common.index)].copy()
    stats = {
        "rows_before": int(sum(document_frequency.values)),
        "rows_after": int(len(exploded)),
        "dropped_tokens": int(len(common)),
        "tokens_before": int(len(document_frequency)),
        "tokens_after": int(len(document_frequency) - len(common)),
        "threshold_records": threshold,
        "median_df_remaining": float(document_frequency.drop(index=common.index, errors="ignore").median()) if len(document_frequency) > len(common) else 0.0,
        "max_df_remaining": int(document_frequency.drop(index=common.index, errors="ignore").max()) if len(document_frequency) > len(common) else 0,
    }
    return exploded, document_frequency, stats


def token_join_candidates(
    s1_tokens: pd.DataFrame,
    target_tokens: pd.DataFrame,
    *,
    max_candidates: int = 30,
) -> pd.DataFrame:
    """Hash-join token postings and return top candidates by shared-token count."""
    joined = s1_tokens.merge(target_tokens, on="token", how="inner", suffixes=("_s1", "_target"),
                             sort=False, copy=False)
    if joined.empty:
        return pd.DataFrame(columns=["source1_entity_id", "candidate_entity_id", "shared_tokens"])
    grouped = (
        joined.groupby(["entity_id_s1", "entity_id_target"], observed=True, sort=False)
        .size().rename("shared_tokens").reset_index()
    )
    grouped = grouped.sort_values(
        ["entity_id_s1", "shared_tokens", "entity_id_target"],
        ascending=[True, False, True], kind="stable",
    )
    grouped = grouped.groupby("entity_id_s1", observed=True, sort=False).head(max_candidates)
    return grouped.rename(columns={
        "entity_id_s1": "source1_entity_id",
        "entity_id_target": "candidate_entity_id",
    })


def phonetic_key_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Long table of source IDs and Metaphone/Soundex keys for exact joins."""
    pieces = []
    for key_type in ("metaphone_key", "soundex_key"):
        part = frame[["entity_id", key_type]].rename(columns={key_type: "key"}).copy()
        part["key_type"] = key_type
        part = part.loc[part["key"].astype(str).str.len() > 0]
        pieces.append(part[["entity_id", "key_type", "key"]])
    return pd.concat(pieces, ignore_index=True)


def phonetic_join_candidates(s1_keys: pd.DataFrame, target_keys: pd.DataFrame) -> pd.DataFrame:
    """Join exact metaphone/soundex keys, aggregate matched channel count."""
    joined = s1_keys.merge(target_keys, on=["key_type", "key"], how="inner",
                           suffixes=("_s1", "_target"), sort=False, copy=False)
    if joined.empty:
        return pd.DataFrame(columns=["source1_entity_id", "candidate_entity_id", "phonetic_channels"])
    grouped = (
        joined.groupby(["entity_id_s1", "entity_id_target"], observed=True, sort=False)["key_type"]
        .nunique().rename("phonetic_channels").reset_index()
    )
    return grouped.rename(columns={
        "entity_id_s1": "source1_entity_id",
        "entity_id_target": "candidate_entity_id",
    })
