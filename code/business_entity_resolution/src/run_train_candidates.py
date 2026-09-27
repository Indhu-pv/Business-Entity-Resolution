"""Generate and evaluate guarded train candidate pairs from verified blockers."""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from blocking import exact_token_frequencies, tokenize_record  # noqa: E402
from run_blocking import assert_limits, peak_working_set_bytes, working_set_bytes  # noqa: E402

CLEAN = ROOT / "dataset" / "clean"
PAIR_DB_DEFAULT = Path(
    r"C:\Users\indhu\AppData\Local\Temp\blocking-pair-preflight-x4fq304j\pair_frequencies.sqlite3"
)
INPUT_COLUMNS = [
    "entity_id", "business_name", "business_address", "country",
    "stripped_core_name", "address_text_core", "metaphone_key", "soundex_key",
]


def check_guard(started: float, args) -> None:
    assert_limits(started, args.max_minutes, args.max_working_set_gib)


def open_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA cache_size = -524288")
    connection.execute("PRAGMA temp_store = FILE")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def verify_pair_database(connection: sqlite3.Connection) -> None:
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    expected = {f"pair_df_s{source}" for source in (1, 2, 3)}
    if not expected.issubset(tables):
        raise ValueError(f"Pair database is missing aggregate tables: {sorted(expected - tables)}")
    for source in (1, 2, 3):
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info(pair_df_s{source})")}
        if not {"pair_key", "df"}.issubset(columns):
            raise ValueError(f"pair_df_s{source} has an unexpected schema: {sorted(columns)}")
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise ValueError(f"Pair database integrity check failed: {integrity}")


def reset_work_tables(connection: sqlite3.Connection) -> None:
    for table in (
        "token_postings_s1", "token_postings_s2", "token_postings_s3",
        "phonetic_postings_s1", "phonetic_postings_s2", "phonetic_postings_s3",
        "train_entities", "ground_truth", "candidate_scores", "token_top_candidates", "final_candidates",
    ):
        connection.execute(f"DROP TABLE IF EXISTS {table}")
    connection.executescript("""
        CREATE TABLE train_entities (
            source INTEGER NOT NULL,
            ordinal INTEGER NOT NULL,
            entity_id TEXT NOT NULL,
            country TEXT NOT NULL,
            business_name TEXT NOT NULL,
            business_address TEXT NOT NULL,
            retained_tokens INTEGER NOT NULL,
            PRIMARY KEY (source, entity_id)
        ) WITHOUT ROWID;
        CREATE TABLE ground_truth (
            source1_entity_id TEXT NOT NULL,
            target_entity_id TEXT NOT NULL,
            PRIMARY KEY (source1_entity_id, target_entity_id)
        ) WITHOUT ROWID;
        CREATE TABLE candidate_scores (
            source1_entity_id TEXT NOT NULL,
            candidate_entity_id TEXT NOT NULL,
            token_pair_count INTEGER NOT NULL DEFAULT 0,
            phonetic_channels INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (source1_entity_id, candidate_entity_id)
        ) WITHOUT ROWID;
        CREATE TABLE final_candidates (
            source1_entity_id TEXT NOT NULL,
            candidate_entity_id TEXT NOT NULL,
            candidate_rank INTEGER NOT NULL,
            token_pair_count INTEGER NOT NULL,
            phonetic_channels INTEGER NOT NULL,
            PRIMARY KEY (source1_entity_id, candidate_entity_id)
        ) WITHOUT ROWID;
        CREATE TABLE token_top_candidates (
            source1_entity_id TEXT NOT NULL,
            candidate_entity_id TEXT NOT NULL,
            token_pair_count INTEGER NOT NULL,
            phonetic_channels INTEGER NOT NULL,
            PRIMARY KEY (source1_entity_id, candidate_entity_id)
        ) WITHOUT ROWID;
        CREATE INDEX final_candidates_order ON final_candidates(source1_entity_id, candidate_rank);
    """)
    for source in (1, 2, 3):
        connection.execute(
            f"CREATE TABLE token_postings_s{source} ("
            "pair_key TEXT NOT NULL, entity_id TEXT NOT NULL, "
            "PRIMARY KEY (pair_key, entity_id)) WITHOUT ROWID"
        )
        connection.execute(
            f"CREATE TABLE phonetic_postings_s{source} ("
            "key_type TEXT NOT NULL, key TEXT NOT NULL, entity_id TEXT NOT NULL, "
            "PRIMARY KEY (key_type, key, entity_id)) WITHOUT ROWID"
        )
    connection.commit()


def load_word_frequencies(
    connection: sqlite3.Connection,
    source: int,
    started: float,
    args,
) -> tuple[int, Counter[str]]:
    table = f"token_df_s{source}"
    metadata = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if metadata:
        has_metadata_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='token_df_metadata'"
        ).fetchone()
        metadata_row = connection.execute(
            "SELECT row_count FROM token_df_metadata WHERE source=?", (source,)
        ).fetchone() if has_metadata_table else None
        if metadata_row:
            row_count = metadata_row[0]
            frequencies = Counter(dict(connection.execute(f"SELECT token, df FROM {table}")))
            print(f"[token DF] S{source}: loaded {len(frequencies):,} cached token frequencies", flush=True)
            check_guard(started, args)
            return row_count, frequencies
        connection.execute(f"DROP TABLE {table}")
        connection.commit()

    path = CLEAN / f"train_source{source}_clean.tsv"
    rows, frequencies, _ = exact_token_frequencies(path, chunk_rows=args.chunk_rows)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS token_df_metadata (source INTEGER PRIMARY KEY, row_count INTEGER NOT NULL)"
    )
    connection.execute(f"CREATE TABLE {table} (token TEXT PRIMARY KEY, df INTEGER NOT NULL) WITHOUT ROWID")
    batch = []
    for token, document_frequency in frequencies.items():
        batch.append((token, document_frequency))
        if len(batch) >= 50_000:
            connection.executemany(f"INSERT INTO {table} VALUES (?, ?)", batch)
            connection.commit()
            batch.clear()
            check_guard(started, args)
    if batch:
        connection.executemany(f"INSERT INTO {table} VALUES (?, ?)", batch)
    connection.execute(
        "INSERT OR REPLACE INTO token_df_metadata(source, row_count) VALUES (?, ?)",
        (source, rows),
    )
    connection.commit()
    check_guard(started, args)
    return rows, frequencies


def build_record_postings(
    connection: sqlite3.Connection,
    source: int,
    rows: int,
    frequencies: Counter[str],
    started: float,
    args,
) -> None:
    path = CLEAN / f"train_source{source}_clean.tsv"
    threshold = max(1, int(rows * args.max_df))
    pair_table = f"pair_df_s{source}"
    token_table = f"token_postings_s{source}"
    phonetic_table = f"phonetic_postings_s{source}"
    connection.execute("DROP TABLE IF EXISTS stage_token_pairs")
    connection.execute("DROP TABLE IF EXISTS stage_phonetic")
    connection.execute("""
        CREATE TEMP TABLE stage_token_pairs (
            pair_key TEXT NOT NULL, entity_id TEXT NOT NULL,
            PRIMARY KEY (pair_key, entity_id)
        ) WITHOUT ROWID
    """)
    connection.execute("""
        CREATE TEMP TABLE stage_phonetic (
            key_type TEXT NOT NULL, key TEXT NOT NULL, entity_id TEXT NOT NULL,
            PRIMARY KEY (key_type, key, entity_id)
        ) WITHOUT ROWID
    """)
    rows_seen = int(connection.execute(
        "SELECT COUNT(*) FROM train_entities WHERE source=?", (source,)
    ).fetchone()[0])
    if rows_seen > rows:
        raise ValueError(f"Checkpoint for S{source} has {rows_seen:,} rows, expected at most {rows:,}")
    completed_before = rows_seen
    started_phase = time.perf_counter()
    for frame in pd.read_csv(
        path, sep="\t", usecols=INPUT_COLUMNS, dtype="string",
        keep_default_na=False, encoding="utf-8", encoding_errors="replace",
        chunksize=args.chunk_rows,
    ):
        if completed_before:
            skipped = min(completed_before, len(frame))
            frame = frame.iloc[skipped:]
            completed_before -= skipped
            if frame.empty:
                del frame
                continue
        frame = frame[INPUT_COLUMNS]
        entity_rows = []
        pair_rows = []
        phonetic_rows = []
        for record in frame.itertuples(index=False, name=None):
            entity_id, name, address, country, core_name, address_core, metaphone, soundex = record
            tokens = tokenize_record(core_name, address_core)
            retained = [token for token in tokens if frequencies[token] <= threshold]
            rarest = sorted(retained, key=lambda token: (frequencies[token], token))[:20]
            entity_rows.append((source, rows_seen + 1, entity_id, country, name, address, len(retained)))
            for first, second in combinations(rarest, 2):
                pair_rows.append(("\x1f".join(sorted((first, second))), entity_id))
            if metaphone:
                phonetic_rows.append(("metaphone_key", metaphone, entity_id))
            if soundex:
                phonetic_rows.append(("soundex_key", soundex, entity_id))
            rows_seen += 1

        connection.executemany(
            "INSERT INTO train_entities VALUES (?, ?, ?, ?, ?, ?, ?)", entity_rows
        )
        connection.executemany("INSERT OR IGNORE INTO stage_token_pairs VALUES (?, ?)", pair_rows)
        connection.executemany("INSERT OR IGNORE INTO stage_phonetic VALUES (?, ?, ?)", phonetic_rows)
        connection.execute(
            f"INSERT OR IGNORE INTO {token_table} (pair_key, entity_id) "
            f"SELECT stage.pair_key, stage.entity_id FROM stage_token_pairs AS stage "
            f"INNER JOIN {pair_table} AS approved ON approved.pair_key = stage.pair_key"
        )
        connection.execute(
            f"INSERT OR IGNORE INTO {phonetic_table} (key_type, key, entity_id) "
            "SELECT key_type, key, entity_id FROM stage_phonetic"
        )
        connection.execute("DELETE FROM stage_token_pairs")
        connection.execute("DELETE FROM stage_phonetic")
        connection.commit()
        if rows_seen % args.progress_records < len(frame) or rows_seen == rows:
            elapsed = time.perf_counter() - started_phase
            print(f"[postings progress] S{source}: records={rows_seen:,}/{rows:,}, "
                  f"elapsed={elapsed/60:.1f} min, working_set={working_set_bytes()/1024**3:.3f} GiB",
                  flush=True)
        check_guard(started, args)
        del frame, entity_rows, pair_rows, phonetic_rows

    if rows_seen != rows:
        raise ValueError(f"Read {rows_seen:,} rows from {path.name}, expected {rows:,}")
    actual_pairs = connection.execute(f"SELECT COUNT(*) FROM {token_table}").fetchone()[0]
    expected_pairs = connection.execute(f"SELECT COALESCE(SUM(df), 0) FROM {pair_table}").fetchone()[0]
    if actual_pairs != expected_pairs:
        raise ValueError(
            f"Reconstructed S{source} record-pair postings ({actual_pairs:,}) do not match "
            f"the verified aggregate table ({expected_pairs:,}); refusing to join"
        )
    print(f"[postings complete] S{source}: pair_postings={actual_pairs:,}, "
          f"phonetic_postings={connection.execute(f'SELECT COUNT(*) FROM {phonetic_table}').fetchone()[0]:,}",
          flush=True)


def load_ground_truth(connection: sqlite3.Connection, started: float, args) -> int:
    path = CLEAN / "train_ground_truth_clean.tsv"
    inserted = 0
    for frame in pd.read_csv(
        path, sep="\t", dtype="string", keep_default_na=False,
        encoding="utf-8", encoding_errors="replace", chunksize=args.chunk_rows,
    ):
        rows = []
        for source1_id, matched_ids in frame[["source1_entity_id", "matched_entity_ids"]].itertuples(index=False, name=None):
            for target_id in matched_ids.split(","):
                target_id = target_id.strip()
                if target_id.startswith(("S2-", "S3-")):
                    rows.append((source1_id, target_id))
        connection.executemany("INSERT OR IGNORE INTO ground_truth VALUES (?, ?)", rows)
        inserted += len(rows)
        connection.commit()
        check_guard(started, args)
    connection.execute("CREATE INDEX IF NOT EXISTS ground_truth_by_target ON ground_truth(target_entity_id)")
    connection.commit()
    print(f"[ground truth] loaded {inserted:,} train match links", flush=True)
    return inserted


def create_batch_tables(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        DROP TABLE IF EXISTS temp.batch_source1;
        DROP TABLE IF EXISTS temp.batch_token_pairs;
        DROP TABLE IF EXISTS temp.batch_phonetic;
        CREATE TEMP TABLE batch_source1 (
            entity_id TEXT PRIMARY KEY, country TEXT NOT NULL, retained_tokens INTEGER NOT NULL
        ) WITHOUT ROWID;
        CREATE TEMP TABLE batch_token_pairs (
            entity_id TEXT NOT NULL, pair_key TEXT NOT NULL,
            PRIMARY KEY(entity_id, pair_key)
        ) WITHOUT ROWID;
        CREATE TEMP TABLE batch_phonetic (
            entity_id TEXT NOT NULL, key_type TEXT NOT NULL, key TEXT NOT NULL,
            PRIMARY KEY(entity_id, key_type, key)
        ) WITHOUT ROWID;
    """)


def add_candidate_scores(connection: sqlite3.Connection, source: int) -> None:
    token_table = f"token_postings_s{source}"
    phonetic_table = f"phonetic_postings_s{source}"
    connection.execute(
        "INSERT INTO candidate_scores "
        "SELECT left_side.entity_id, right_side.entity_id, COUNT(*), 0 "
        f"FROM batch_token_pairs AS left_side INNER JOIN {token_table} AS right_side "
        "ON right_side.pair_key = left_side.pair_key "
        "GROUP BY left_side.entity_id, right_side.entity_id "
        "ON CONFLICT(source1_entity_id, candidate_entity_id) DO UPDATE SET "
        "token_pair_count = token_pair_count + excluded.token_pair_count"
    )
    connection.execute(
        "INSERT INTO candidate_scores "
        "SELECT left_side.entity_id, right_side.entity_id, 0, COUNT(DISTINCT left_side.key_type) "
        f"FROM batch_phonetic AS left_side INNER JOIN {phonetic_table} AS right_side "
        "ON right_side.key_type = left_side.key_type AND right_side.key = left_side.key "
        "GROUP BY left_side.entity_id, right_side.entity_id "
        "ON CONFLICT(source1_entity_id, candidate_entity_id) DO UPDATE SET "
        "phonetic_channels = MAX(phonetic_channels, excluded.phonetic_channels)"
    )


def add_top_union_candidates(connection: sqlite3.Connection, batch_ids: list[str], maximum: int) -> None:
    if not batch_ids:
        return
    connection.execute("DELETE FROM batch_source1")
    connection.executemany(
        "INSERT INTO batch_source1 SELECT entity_id, country, retained_tokens "
        "FROM train_entities WHERE source = 1 AND entity_id = ?",
        ((entity_id,) for entity_id in batch_ids),
    )
    placeholders = ",".join("?" for _ in batch_ids)
    connection.execute(
        "INSERT OR IGNORE INTO final_candidates "
        "SELECT source1_entity_id, candidate_entity_id, candidate_rank, token_pair_count, phonetic_channels "
        "FROM (SELECT scores.source1_entity_id, scores.candidate_entity_id, scores.token_pair_count, "
        "scores.phonetic_channels, ROW_NUMBER() OVER (PARTITION BY scores.source1_entity_id "
        "ORDER BY scores.token_pair_count DESC, scores.phonetic_channels DESC, scores.candidate_entity_id) "
        "AS candidate_rank FROM candidate_scores AS scores "
        f"WHERE scores.source1_entity_id IN ({placeholders})) WHERE candidate_rank <= ?",
        (*batch_ids, maximum),
    )


def generate_candidates(connection: sqlite3.Connection, frequencies: Counter[str], rows: int,
                        started: float, args) -> dict:
    create_batch_tables(connection)
    threshold = max(1, int(rows * args.max_df))
    path = CLEAN / "train_source1_clean.tsv"
    seen = 0
    batch_ids: list[str] = []
    batch_token_rows: list[tuple[str, str]] = []
    batch_phonetic_rows: list[tuple[str, str, str]] = []
    phase_started = time.perf_counter()
    blocker_hits = {"token_hits": 0, "phonetic_hits": 0, "union_hits_before_cap": 0}
    both_missed = []
    for frame in pd.read_csv(
        path, sep="\t", usecols=INPUT_COLUMNS, dtype="string",
        keep_default_na=False, encoding="utf-8", encoding_errors="replace",
        chunksize=args.batch_rows,
    ):
        frame = frame[INPUT_COLUMNS]
        for entity_id, _, _, country, core_name, address_core, metaphone, soundex in frame.itertuples(index=False, name=None):
            retained = [
                token for token in tokenize_record(core_name, address_core)
                if frequencies[token] <= threshold
            ]
            rarest = sorted(retained, key=lambda token: (frequencies[token], token))[:20]
            pair_keys = ["\x1f".join(sorted(pair)) for pair in combinations(rarest, 2)]
            batch_ids.append(entity_id)
            batch_token_rows.extend((entity_id, key) for key in pair_keys)
            if metaphone:
                batch_phonetic_rows.append((entity_id, "metaphone_key", metaphone))
            if soundex:
                batch_phonetic_rows.append((entity_id, "soundex_key", soundex))
            seen += 1

        connection.executemany("INSERT INTO batch_source1 VALUES (?, ?, ?)", [
            (entity_id, country, retained_count)
            for entity_id, country, retained_count in connection.execute(
                "SELECT entity_id, country, retained_tokens FROM train_entities WHERE source=1 AND entity_id IN ("
                + ",".join("?" for _ in batch_ids) + ")", batch_ids
            )
        ])
        connection.executemany("INSERT OR IGNORE INTO batch_token_pairs VALUES (?, ?)", batch_token_rows)
        connection.executemany("INSERT OR IGNORE INTO batch_phonetic VALUES (?, ?, ?)", batch_phonetic_rows)
        for target_source in (2, 3):
            add_candidate_scores(connection, target_source)
        placeholders = ",".join("?" for _ in batch_ids)
        connection.execute(
            "INSERT OR IGNORE INTO token_top_candidates "
            "SELECT source1_entity_id, candidate_entity_id, token_pair_count, phonetic_channels "
            "FROM (SELECT scores.source1_entity_id, scores.candidate_entity_id, scores.token_pair_count, "
            "scores.phonetic_channels, ROW_NUMBER() OVER (PARTITION BY scores.source1_entity_id, "
            "substr(scores.candidate_entity_id, 1, 2) ORDER BY scores.token_pair_count DESC, "
            "scores.phonetic_channels DESC, scores.candidate_entity_id) AS candidate_rank "
            f"FROM candidate_scores AS scores WHERE scores.source1_entity_id IN ({placeholders}) "
            "AND scores.token_pair_count > 0) WHERE candidate_rank <= ?",
            (*batch_ids, args.max_candidates),
        )
        blocker_hits["token_hits"] += connection.execute(
            "SELECT COUNT(*) FROM ground_truth AS truth "
            "INNER JOIN batch_source1 AS batch ON batch.entity_id=truth.source1_entity_id "
            "INNER JOIN token_top_candidates AS scores ON scores.source1_entity_id=truth.source1_entity_id "
            "AND scores.candidate_entity_id=truth.target_entity_id"
        ).fetchone()[0]
        blocker_hits["phonetic_hits"] += connection.execute(
            "SELECT COUNT(*) FROM ground_truth AS truth "
            "INNER JOIN batch_source1 AS batch ON batch.entity_id=truth.source1_entity_id "
            "INNER JOIN candidate_scores AS scores ON scores.source1_entity_id=truth.source1_entity_id "
            "AND scores.candidate_entity_id=truth.target_entity_id WHERE scores.phonetic_channels > 0"
        ).fetchone()[0]
        blocker_hits["union_hits_before_cap"] += connection.execute(
            "SELECT COUNT(*) FROM ground_truth AS truth "
            "INNER JOIN batch_source1 AS batch ON batch.entity_id=truth.source1_entity_id "
            "INNER JOIN candidate_scores AS scores ON scores.source1_entity_id=truth.source1_entity_id "
            "AND scores.candidate_entity_id=truth.target_entity_id"
        ).fetchone()[0]
        connection.execute(
            "DELETE FROM candidate_scores WHERE source1_entity_id IN ("
            + placeholders + ") AND token_pair_count > 0 AND phonetic_channels = 0 "
            "AND NOT EXISTS (SELECT 1 FROM token_top_candidates AS top "
            "WHERE top.source1_entity_id=candidate_scores.source1_entity_id "
            "AND top.candidate_entity_id=candidate_scores.candidate_entity_id)",
            batch_ids,
        )
        connection.execute(
            "UPDATE candidate_scores SET token_pair_count = 0 WHERE source1_entity_id IN ("
            + placeholders + ") AND token_pair_count > 0 AND NOT EXISTS ("
            "SELECT 1 FROM token_top_candidates AS top "
            "WHERE top.source1_entity_id=candidate_scores.source1_entity_id "
            "AND top.candidate_entity_id=candidate_scores.candidate_entity_id)",
            batch_ids,
        )
        remaining_examples = 10 - len(both_missed)
        if remaining_examples > 0:
            both_missed.extend(connection.execute(
                "SELECT truth.source1_entity_id, truth.target_entity_id FROM ground_truth AS truth "
                "INNER JOIN batch_source1 AS batch ON batch.entity_id=truth.source1_entity_id "
                "LEFT JOIN candidate_scores AS scores ON scores.source1_entity_id=truth.source1_entity_id "
                "AND scores.candidate_entity_id=truth.target_entity_id "
                "WHERE scores.source1_entity_id IS NULL "
                "ORDER BY truth.source1_entity_id, truth.target_entity_id LIMIT ?",
                (remaining_examples,),
            ).fetchall())
        add_top_union_candidates(connection, batch_ids, args.max_candidates)
        connection.execute("DELETE FROM candidate_scores WHERE source1_entity_id IN ("
                           + ",".join("?" for _ in batch_ids) + ")", batch_ids)
        connection.execute("DELETE FROM batch_source1")
        connection.execute("DELETE FROM batch_token_pairs")
        connection.execute("DELETE FROM batch_phonetic")
        connection.commit()
        batch_ids.clear()
        batch_token_rows.clear()
        batch_phonetic_rows.clear()
        if seen % args.progress_records < len(frame) or seen == rows:
            elapsed = time.perf_counter() - phase_started
            print(f"[candidate join progress] S1 records={seen:,}/{rows:,}, "
                  f"elapsed={elapsed/60:.1f} min, rate={seen/max(elapsed, 1):,.0f} records/s, "
                  f"working_set={working_set_bytes()/1024**3:.3f} GiB", flush=True)
        check_guard(started, args)
        del frame
    if seen != rows:
        raise ValueError(f"Candidate join scanned {seen:,} S1 rows, expected {rows:,}")
    blocker_hits["both_missed"] = both_missed
    return blocker_hits


def calculate_metrics(connection: sqlite3.Connection, blocker_hits: dict) -> dict:
    total_truth = connection.execute("SELECT COUNT(*) FROM ground_truth").fetchone()[0]
    metrics = {"true_links": total_truth, **blocker_hits}
    metrics["union_hits"] = connection.execute(
        "SELECT COUNT(*) FROM ground_truth AS truth INNER JOIN final_candidates AS candidates "
        "ON candidates.source1_entity_id=truth.source1_entity_id "
        "AND candidates.candidate_entity_id=truth.target_entity_id"
    ).fetchone()[0]
    metrics["average_candidates"] = connection.execute(
        "SELECT CAST((SELECT COUNT(*) FROM final_candidates) AS REAL) / "
        "(SELECT COUNT(*) FROM train_entities WHERE source=1)"
    ).fetchone()[0]
    metrics["low_token"] = connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(CASE WHEN candidates.candidate_entity_id IS NOT NULL THEN 1 ELSE 0 END), 0) "
        "FROM ground_truth AS truth INNER JOIN train_entities AS entity "
        "ON entity.source=1 AND entity.entity_id=truth.source1_entity_id "
        "LEFT JOIN final_candidates AS candidates ON candidates.source1_entity_id=truth.source1_entity_id "
        "AND candidates.candidate_entity_id=truth.target_entity_id WHERE entity.retained_tokens < 2"
    ).fetchone()
    metrics["country"] = connection.execute(
        "SELECT entity.country, COUNT(*), COALESCE(SUM(CASE WHEN candidates.candidate_entity_id IS NOT NULL "
        "THEN 1 ELSE 0 END), 0) FROM ground_truth AS truth "
        "INNER JOIN train_entities AS entity ON entity.source=1 AND entity.entity_id=truth.source1_entity_id "
        "LEFT JOIN final_candidates AS candidates ON candidates.source1_entity_id=truth.source1_entity_id "
        "AND candidates.candidate_entity_id=truth.target_entity_id GROUP BY entity.country ORDER BY entity.country"
    ).fetchall()
    metrics["candidate_count"] = connection.execute("SELECT COUNT(*) FROM final_candidates").fetchone()[0]
    metrics["source1_count"] = connection.execute(
        "SELECT COUNT(*) FROM train_entities WHERE source=1"
    ).fetchone()[0]
    return metrics


def recall(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def write_candidates(connection: sqlite3.Connection, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["source1_entity_id", "candidate_entity_ids"])
        cursor = connection.execute(
            "SELECT entity.entity_id, candidates.candidate_entity_id "
            "FROM train_entities AS entity LEFT JOIN final_candidates AS candidates "
            "ON candidates.source1_entity_id=entity.entity_id "
            "WHERE entity.source=1 ORDER BY entity.ordinal, candidates.candidate_rank"
        )
        current_id = None
        candidates = []
        for entity_id, candidate_id in cursor:
            if current_id is not None and entity_id != current_id:
                writer.writerow([current_id, ",".join(candidates)])
                candidates = []
            current_id = entity_id
            if candidate_id is not None:
                candidates.append(candidate_id)
        if current_id is not None:
            writer.writerow([current_id, ",".join(candidates)])


def write_report(metrics: dict, elapsed: float, peak_gib: float, examples: list[dict]) -> None:
    total = metrics["true_links"]
    low_total, low_hits = metrics["low_token"]
    lines = [
        "# Train Blocking Results\n\n",
        "Candidate generation used the verified pair-key DF tables as the approved pair vocabulary and built record-level postings from cleaned train records. Token-pair and phonetic channels were joined independently in bounded S1 batches. The union was deduplicated and capped at 30 candidates per S1, ranked by shared pair count, then phonetic channel count, then candidate ID. No test candidates were generated.\n\n",
        "## Recall and candidate volume\n\n",
        "| Metric | Result |\n|---|---:|\n",
        f"| Overall capped union recall | {recall(metrics['union_hits'], total):.4%} ({metrics['union_hits']:,}/{total:,}) |\n",
        f"| Token-pair recall (before union cap) | {recall(metrics['token_hits'], total):.4%} ({metrics['token_hits']:,}/{total:,}) |\n",
        f"| Phonetic recall (before union cap) | {recall(metrics['phonetic_hits'], total):.4%} ({metrics['phonetic_hits']:,}/{total:,}) |\n",
        f"| Recall among S1 records with fewer than 2 retained tokens | {recall(low_hits, low_total):.4%} ({low_hits:,}/{low_total:,} true links) |\n",
        f"| Average candidates per S1 entity | {metrics['average_candidates']:.3f} |\n",
        f"| S1 entities | {metrics['source1_count']:,} |\n",
        f"| Candidate pairs written | {metrics['candidate_count']:,} |\n",
        "\n## Capped union recall by S1 country\n\n| Country | True links | Recalled links | Recall |\n|---|---:|---:|---:|\n",
    ]
    for country, denominator, numerator in metrics["country"]:
        lines.append(f"| {country} | {denominator:,} | {numerator:,} | {recall(numerator, denominator):.4%} |\n")
    lines.extend(["\n## Ten true links missed by both blockers\n\n",
                  "Raw values are shown for each S1 record and its true target.\n\n",
                  "| S1 ID | S1 name | S1 address | True target ID | Target name | Target address |\n|---|---|---|---|---|---|\n"])
    for example in examples:
        lines.append("| " + " | ".join(str(example[key]).replace("|", "\\|").replace("\n", " ") for key in (
            "source1_id", "source1_name", "source1_address", "target_id", "target_name", "target_address"
        )) + " |\n")
    lines.extend(["\n## Resource status\n\n",
                  f"- Elapsed wall time: {elapsed/60:.2f} minutes.\n",
                  f"- Peak process working set: {peak_gib:.3f} GiB.\n",
                  "- 30-minute wall-clock and 5.5 GiB working-set guards were enabled.\n",
                  "- No test candidate generation was run.\n"])
    (ROOT / "blocking_report.md").write_text("".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair-db", type=Path, default=PAIR_DB_DEFAULT)
    parser.add_argument("--max-candidates", type=int, default=30)
    parser.add_argument("--max-df", type=float, default=0.0005)
    parser.add_argument("--chunk-rows", type=int, default=5_000)
    parser.add_argument("--batch-rows", type=int, default=500)
    parser.add_argument("--progress-records", type=int, default=100_000)
    parser.add_argument("--resume-work", action="store_true",
                        help="Continue from committed source-posting checkpoints in the pair DB")
    parser.add_argument("--max-minutes", type=float, default=30)
    parser.add_argument("--max-working-set-gib", type=float, default=5.5)
    args = parser.parse_args()

    started = time.perf_counter()
    if not args.pair_db.is_file():
        raise FileNotFoundError(f"Verified pair-frequency database not found: {args.pair_db}")
    connection = open_database(args.pair_db)
    try:
        verify_pair_database(connection)
        if args.resume_work:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            required = {"train_entities", "candidate_scores", "token_top_candidates", "final_candidates"}
            if not required.issubset(tables):
                raise ValueError(f"Resume database lacks work tables: {sorted(required - tables)}")
            print("[resume] keeping committed entity and posting tables", flush=True)
        else:
            reset_work_tables(connection)
        frequency_maps = {}
        row_counts = {}
        for source in (1, 2, 3):
            print(f"[token DF] scanning S{source}", flush=True)
            row_counts[source], frequency_maps[source] = load_word_frequencies(
                connection, source, started, args
            )
            print(f"[token DF] S{source}: rows={row_counts[source]:,}, "
                  f"vocabulary={len(frequency_maps[source]):,}", flush=True)
        for source in (1, 2, 3):
            saved_rows = connection.execute(
                "SELECT COUNT(*) FROM train_entities WHERE source=?", (source,)
            ).fetchone()[0] if args.resume_work else 0
            if saved_rows >= row_counts[source]:
                print(f"[record postings] S{source}: checkpoint complete ({saved_rows:,} rows)", flush=True)
                continue
            print(f"[record postings] building S{source}", flush=True)
            build_record_postings(
                connection, source, row_counts[source], frequency_maps[source], started, args
            )
        has_ground_truth = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ground_truth'"
        ).fetchone()
        if has_ground_truth and connection.execute("SELECT COUNT(*) FROM ground_truth").fetchone()[0]:
            print("[ground truth] keeping committed links", flush=True)
        else:
            load_ground_truth(connection, started, args)
        print("[candidate generation] joining token-pair and phonetic channels", flush=True)
        blocker_hits = generate_candidates(connection, frequency_maps[1], row_counts[1], started, args)
        metrics = calculate_metrics(connection, blocker_hits)
        examples = []
        for source1_id, target_id in metrics["both_missed"]:
            source1 = connection.execute(
                "SELECT business_name, business_address FROM train_entities WHERE source=1 AND entity_id=?",
                (source1_id,),
            ).fetchone()
            target_source = 2 if target_id.startswith("S2-") else 3
            target = connection.execute(
                "SELECT business_name, business_address FROM train_entities WHERE source=? AND entity_id=?",
                (target_source, target_id),
            ).fetchone()
            examples.append({
                "source1_id": source1_id,
                "source1_name": source1[0] if source1 else "",
                "source1_address": source1[1] if source1 else "",
                "target_id": target_id,
                "target_name": target[0] if target else "",
                "target_address": target[1] if target else "",
            })
        output = CLEAN / "train_candidate_pairs.tsv"
        write_candidates(connection, output)
        elapsed = time.perf_counter() - started
        peak_gib = peak_working_set_bytes() / 1024**3
        write_report(metrics, elapsed, peak_gib, examples)
        total = metrics["true_links"]
        low_total, low_hits = metrics["low_token"]
        print("\n=== Train blocking evaluation ===")
        print(f"Overall capped union recall: {recall(metrics['union_hits'], total):.4%} "
              f"({metrics['union_hits']:,}/{total:,})")
        print(f"Token-pair recall before cap: {recall(metrics['token_hits'], total):.4%} "
              f"({metrics['token_hits']:,}/{total:,})")
        print(f"Phonetic recall before cap: {recall(metrics['phonetic_hits'], total):.4%} "
              f"({metrics['phonetic_hits']:,}/{total:,})")
        print(f"Recall for S1 records with <2 retained tokens: {recall(low_hits, low_total):.4%} "
              f"({low_hits:,}/{low_total:,})")
        print(f"Average candidate-set size: {metrics['average_candidates']:.3f}")
        print("Recall by country:")
        for country, denominator, numerator in metrics["country"]:
            print(f"  {country}: {recall(numerator, denominator):.4%} ({numerator:,}/{denominator:,})")
        print("Ten examples missed by both blockers:")
        for example in examples:
            print(f"  {example['source1_id']} {example['source1_name']!r} / "
                  f"{example['source1_address']!r} -> {example['target_id']} "
                  f"{example['target_name']!r} / {example['target_address']!r}")
        print(f"Output: {output}")
        print(f"Report: {ROOT / 'blocking_report.md'}")
        print(f"Elapsed: {elapsed/60:.2f} min; peak working set: {peak_gib:.3f} GiB")
    finally:
        connection.close()


if __name__ == "__main__":
    main()