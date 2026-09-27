"""Preflight and run explicit token/phonetic hash joins on train data."""
from __future__ import annotations

import argparse
import ctypes
import gc
import os
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from ctypes import wintypes
from itertools import combinations
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from blocking import (  # noqa: E402
    BLOCK_COLUMNS,
    CATEGORY_COLUMNS,
    exact_token_frequencies,
    phonetic_join_candidates,
    phonetic_key_table,
    tokenize_record,
    token_join_candidates,
    token_rows,
    token_table,
)

CLEAN = ROOT / "dataset" / "clean"


def working_set_bytes() -> int:
    if os.name != "nt":
        return 0

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    psapi = ctypes.WinDLL("Psapi.dll")
    kernel = ctypes.WinDLL("Kernel32.dll")
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return 0
    return int(counters.WorkingSetSize)


def peak_working_set_bytes() -> int:
    if os.name != "nt":
        return working_set_bytes()

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    psapi = ctypes.WinDLL("Psapi.dll")
    kernel = ctypes.WinDLL("Kernel32.dll")
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return 0
    return int(counters.PeakWorkingSetSize)


def assert_limits(started: float, max_minutes: float, max_gib: float) -> None:
    elapsed = time.perf_counter() - started
    memory = working_set_bytes()
    if elapsed > max_minutes * 60:
        raise TimeoutError(f"Hard runtime guard exceeded: {elapsed/60:.1f} minutes")
    if memory > max_gib * 1024**3:
        raise MemoryError(f"Hard working-set guard exceeded: {memory/1024**3:.3f} GiB")


def load_trimmed(source: int, *, chunk_rows: int | None = None) -> pd.DataFrame:
    path = CLEAN / f"train_source{source}_clean.tsv"
    return pd.read_csv(
        path, sep="\t", usecols=BLOCK_COLUMNS, dtype=CATEGORY_COLUMNS,
        keep_default_na=False, encoding="utf-8", encoding_errors="replace",
        chunksize=chunk_rows,
    ) if chunk_rows else pd.read_csv(
        path, sep="\t", usecols=BLOCK_COLUMNS, dtype=CATEGORY_COLUMNS,
        keep_default_na=False, encoding="utf-8", encoding_errors="replace",
    )


def frame_bytes(frame: pd.DataFrame) -> int:
    return int(frame.memory_usage(index=True, deep=True).sum())


def frequency_distribution(frequencies: Counter[str]) -> dict[str, int]:
    buckets = {"1": 0, "2-5": 0, "6-20": 0, "21-100": 0, "100+": 0}
    for document_frequency in frequencies.values():
        if document_frequency == 1:
            buckets["1"] += 1
        elif document_frequency <= 5:
            buckets["2-5"] += 1
        elif document_frequency <= 20:
            buckets["6-20"] += 1
        elif document_frequency <= 100:
            buckets["21-100"] += 1
        else:
            buckets["100+"] += 1
    return buckets


def count_pair_coverage(
    path: Path,
    max_df: float,
    chunk_rows: int,
    frequencies: Counter[str] | None = None,
    total_rows: int | None = None,
) -> dict:
    if frequencies is None or total_rows is None:
        total_rows, frequencies, _ = exact_token_frequencies(path, chunk_rows=chunk_rows)
    threshold = max(1, int(total_rows * max_df))
    fewer_than_two = 0
    rows_seen = 0
    for frame in pd.read_csv(
        path, sep="\t", usecols=["stripped_core_name", "address_text_core"],
        dtype={"stripped_core_name": "category", "address_text_core": "category"},
        keep_default_na=False, encoding="utf-8", encoding_errors="replace",
        chunksize=chunk_rows,
    ):
        for name, address in zip(frame["stripped_core_name"], frame["address_text_core"]):
            surviving = sum(
                frequencies[token] <= threshold
                for token in tokenize_record(name, address)
            )
            fewer_than_two += surviving < 2
            rows_seen += 1
        del frame
    if rows_seen != total_rows:
        raise ValueError(f"Row count changed while scanning {path.name}: {rows_seen} != {total_rows}")
    return {
        "rows": rows_seen,
        "threshold": threshold,
        "fewer_than_two_tokens": fewer_than_two,
        "fewer_than_two_tokens_pct": 100 * fewer_than_two / rows_seen if rows_seen else 0.0,
    }


def update_coverage_report(max_df: float, chunk_rows: int) -> None:
    report_path = ROOT / "blocking_preflight_report.md"
    if not report_path.exists():
        raise FileNotFoundError("Run the estimate-only preflight first to create blocking_preflight_report.md")
    rows = []
    for src in (1, 2, 3):
        path = CLEAN / f"train_source{src}_clean.tsv"
        stats = count_pair_coverage(path, max_df, chunk_rows)
        rows.append(
            f"| Train S{src} | {stats['rows']:,} | {stats['fewer_than_two_tokens']:,} | "
            f"{stats['fewer_than_two_tokens_pct']:.2f}% |\n"
        )
        print(f"[pair coverage] S{src}: fewer_than_two={stats['fewer_than_two_tokens']:,}/"
              f"{stats['rows']:,} ({stats['fewer_than_two_tokens_pct']:.2f}%)", flush=True)
    section = (
        "### Records unable to emit a token pair\n\n"
        "These records have fewer than two tokens remaining after the frequency filter and therefore cannot match through token-pair blocking. They require another blocker, such as phonetic matching. This is a minimum fallback count; records with two or more tokens can still have no matching pair in the other source.\n\n"
        "| Source | Records | Fewer than 2 retained tokens | Percentage |\n"
        "|---|---:|---:|---:|\n"
        + "".join(rows)
        + "\n"
    )
    text = report_path.read_text(encoding="utf-8")
    marker = "### Token-pair key counts\n"
    if marker not in text:
        raise ValueError("Expected token-pair section was not found in the preflight report")
    if "### Records unable to emit a token pair" in text:
        start = text.index("### Records unable to emit a token pair")
        end = text.index(marker, start)
        text = text[:start] + section + text[end:]
    else:
        text = text.replace(marker, section + marker, 1)
    report_path.write_text(text, encoding="utf-8")


def pair_frequency_preflight(
    path: Path,
    frequencies: Counter[str],
    threshold: int,
    connection: sqlite3.Connection,
    source: int,
    chunk_rows: int,
    started: float,
    max_minutes: float,
    max_working_set_gib: float,
    progress_records: int,
    *,
    batch_records: int = 5_000,
) -> dict:
    """Count retained rare-token pairs per source, without joining records."""
    table = f"pair_df_s{source}"
    connection.execute(
        f"CREATE TABLE {table} (pair_key TEXT PRIMARY KEY, df INTEGER NOT NULL) WITHOUT ROWID"
    )
    upsert = (
        f"INSERT INTO {table} (pair_key, df) VALUES (?, ?) "
        "ON CONFLICT(pair_key) DO UPDATE SET df = df + excluded.df"
    )
    pair_counts: Counter[str] = Counter()
    rows_seen = 0
    fewer_than_two_tokens = 0
    pair_postings_seen = 0
    phase_started = time.perf_counter()

    def flush() -> None:
        if pair_counts:
            connection.executemany(upsert, pair_counts.items())
            connection.commit()
            pair_counts.clear()

    for frame in pd.read_csv(
        path, sep="\t", usecols=["stripped_core_name", "address_text_core"],
        dtype={"stripped_core_name": "category", "address_text_core": "category"},
        keep_default_na=False, encoding="utf-8", encoding_errors="replace",
        chunksize=chunk_rows,
    ):
        for name, address in zip(frame["stripped_core_name"], frame["address_text_core"]):
            retained = [
                token for token in tokenize_record(name, address)
                if frequencies[token] <= threshold
            ]
            if len(retained) < 2:
                fewer_than_two_tokens += 1
            rarest = sorted(retained, key=lambda token: (frequencies[token], token))[:20]
            for first, second in combinations(rarest, 2):
                pair_counts["\x1f".join(sorted((first, second)))] += 1
                pair_postings_seen += 1
            rows_seen += 1
            if rows_seen % batch_records == 0:
                flush()
            if progress_records > 0 and rows_seen % progress_records == 0:
                elapsed = time.perf_counter() - phase_started
                print(f"[pair preflight progress] S{source}: records={rows_seen:,}, "
                      f"elapsed={elapsed/60:.1f} min, "
                      f"rate={rows_seen/max(elapsed, 1):,.0f} records/s, "
                      f"pair_postings_generated={pair_postings_seen:,}, "
                      f"pending_pair_keys={len(pair_counts):,}, "
                      f"working_set={working_set_bytes()/1024**3:.3f} GiB", flush=True)
        del frame
        flush()
        assert_limits(started, max_minutes, max_working_set_gib)

    flush()
    pair_count, posting_count, maximum_df = connection.execute(
        f"SELECT COUNT(*), COALESCE(SUM(df), 0), COALESCE(MAX(df), 0) FROM {table}"
    ).fetchone()
    return {
        "rows": rows_seen,
        "fewer_than_two_tokens": fewer_than_two_tokens,
        "fewer_than_two_tokens_pct": 100 * fewer_than_two_tokens / rows_seen if rows_seen else 0.0,
        "unique_pairs": int(pair_count),
        "pair_postings": int(posting_count),
        "max_pair_df": int(maximum_df),
        "table": table,
    }


def preflight(args) -> dict:
    paths = {src: CLEAN / f"train_source{src}_clean.tsv" for src in (1, 2, 3)}
    result = {"max_df": args.max_df, "frames": {}, "tokens": {}, "frequency_maps": {}, "pairs": {}}
    started = time.perf_counter()
    for src, path in paths.items():
        frame = pd.read_csv(
            path, sep="\t", usecols=BLOCK_COLUMNS, dtype=CATEGORY_COLUMNS,
            keep_default_na=False, encoding="utf-8", encoding_errors="replace",
            nrows=args.memory_sample_rows,
        )
        size = frame_bytes(frame)
        result["frames"][src] = {
            "sample_rows": len(frame),
            "sample_bytes": size,
            "estimated_gib": 0.0,
        }
        print(f"[trimmed sample] S{src}: rows_sampled={len(frame):,}, columns={len(frame.columns)}, "
              f"sample_memory={size/1024**3:.3f} GiB", flush=True)
        del frame
        gc.collect()
        assert_limits(started, args.max_minutes, args.max_working_set_gib)

    # Token document-frequency preflight is streaming and keeps only scalar counts.
    for src, path in paths.items():
        scan_start = time.perf_counter()
        rows, frequencies, chunks = exact_token_frequencies(path, chunk_rows=args.chunk_rows)
        threshold = max(1, int(rows * args.max_df))
        dropped = sum(1 for count in frequencies.values() if count > threshold)
        remaining_histogram = Counter(count for count in frequencies.values() if count <= threshold)
        df_distribution = frequency_distribution(frequencies)
        remaining_total = sum(remaining_histogram.values())
        remaining_postings = sum(count * n_tokens for count, n_tokens in remaining_histogram.items())
        median_position = (remaining_total - 1) // 2
        cumulative = 0
        median_remaining = 0
        for frequency, frequency_count in sorted(remaining_histogram.items()):
            cumulative += frequency_count
            if cumulative > median_position:
                median_remaining = frequency
                break
        average_keys = sum(frequencies.values()) / rows if rows else 0.0
        result["tokens"][src] = {
            "rows": rows,
            "chunks": chunks,
            "unique_tokens": len(frequencies),
            "postings": sum(frequencies.values()),
            "dropped_tokens": dropped,
            "remaining_tokens": sum(remaining_histogram.values()),
            "remaining_postings": remaining_postings,
            "remaining_median_df": float(median_remaining),
            "remaining_max_df": max(remaining_histogram, default=0),
            "threshold_records": threshold,
            "df_distribution": df_distribution,
            "avg_tokens_per_record": average_keys,
            "elapsed_seconds": time.perf_counter() - scan_start,
        }
        result["frames"][src]["rows"] = rows
        result["frames"][src]["estimated_gib"] = (
            result["frames"][src]["sample_bytes"] / max(result["frames"][src]["sample_rows"], 1)
            * rows / 1024**3
        )
        print(f"[token preflight] S{src}: rows={rows:,}, chunks={chunks:,}, "
              f"exploded_rows={sum(frequencies.values()):,}, unique_tokens={len(frequencies):,}, "
              f"df_threshold={threshold:,}, dropped={dropped:,}, "
              f"remaining_vocabulary={result['tokens'][src]['remaining_tokens']:,}, "
              f"remaining_median_df={result['tokens'][src]['remaining_median_df']:.0f}, "
              f"remaining_postings={remaining_postings:,}, "
              f"remaining_max_df={max(remaining_histogram, default=0):,}, "
              f"elapsed={result['tokens'][src]['elapsed_seconds']:.1f}s, "
              f"working_set={working_set_bytes()/1024**3:.3f} GiB", flush=True)
        result["frequency_maps"][src] = frequencies
        del remaining_histogram
        gc.collect()
        assert_limits(started, args.max_minutes, args.max_working_set_gib)
    # Estimate raw single-token join rows without joining source records.
    df_s1 = result["frequency_maps"][1]
    s1_threshold = result["tokens"][1]["threshold_records"]
    for target in (2, 3):
        df_target = result["frequency_maps"][target]
        target_threshold = result["tokens"][target]["threshold_records"]
        estimated_pairs = 0
        shared_tokens = 0
        for token, df1 in df_s1.items():
            df_target_value = df_target.get(token, 0)
            if df1 <= s1_threshold and 0 < df_target_value <= target_threshold:
                estimated_pairs += df1 * df_target_value
                shared_tokens += 1
        result["tokens"][target]["estimated_join_rows"] = estimated_pairs
        result["tokens"][target]["shared_retained_tokens"] = shared_tokens
        print(f"[join estimate] S1 x S{target}: shared_retained_tokens={shared_tokens:,}, "
              f"estimated exact-join rows={estimated_pairs:,}; "
              f"working_set={working_set_bytes()/1024**3:.3f} GiB", flush=True)
        assert_limits(started, args.max_minutes, args.max_working_set_gib)

    # Count pair-key document frequencies on disk, then join only these compact
    # frequency tables to estimate raw pair-key join rows.
    temporary_directory = None
    if args.resume_pair_db:
        database = Path(args.resume_pair_db)
        if not database.is_file():
            raise FileNotFoundError(f"Pair-frequency database not found: {database}")
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        expected_tables = {f"pair_df_s{src}" for src in (1, 2, 3)}
        if not expected_tables.issubset(tables):
            connection.close()
            raise ValueError(f"Resume database is missing tables: {sorted(expected_tables - tables)}")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            connection.close()
            raise ValueError(f"Resume database integrity check failed: {integrity}")
        print(f"[pair preflight] resuming verified pair tables from {database}", flush=True)
    else:
        temporary_directory = tempfile.TemporaryDirectory(prefix="blocking-pair-preflight-")
        database = Path(temporary_directory.name) / "pair_frequencies.sqlite3"
        connection = sqlite3.connect(database)
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute("PRAGMA cache_size = -65536")
    try:
        for src, path in paths.items():
            stats = result["tokens"][src]
            if args.resume_pair_db:
                table = f"pair_df_s{src}"
                pair_count, posting_count, maximum_df = connection.execute(
                    f"SELECT COUNT(*), COALESCE(SUM(df), 0), COALESCE(MAX(df), 0) FROM {table}"
                ).fetchone()
                pair_stats = {
                    "rows": stats["rows"],
                    "unique_pairs": int(pair_count),
                    "pair_postings": int(posting_count),
                    "max_pair_df": int(maximum_df),
                    "table": table,
                }
                coverage = count_pair_coverage(
                    path, args.max_df, args.chunk_rows,
                    result["frequency_maps"][src], stats["rows"],
                )
                pair_stats.update({
                    "fewer_than_two_tokens": coverage["fewer_than_two_tokens"],
                    "fewer_than_two_tokens_pct": coverage["fewer_than_two_tokens_pct"],
                })
            else:
                pair_stats = pair_frequency_preflight(
                    path,
                    result["frequency_maps"][src],
                    stats["threshold_records"],
                    connection,
                    src,
                    args.chunk_rows,
                    started,
                    args.max_minutes,
                    args.max_working_set_gib,
                    args.pair_progress_records,
                )
            result["pairs"][src] = pair_stats
            print(f"[pair preflight] S{src}: unique_pairs={pair_stats['unique_pairs']:,}, "
                  f"pair_postings={pair_stats['pair_postings']:,}, "
                  f"max_pair_df={pair_stats['max_pair_df']:,}, "
                  f"fewer_than_two={pair_stats['fewer_than_two_tokens']:,}/"
                  f"{pair_stats['rows']:,} ({pair_stats['fewer_than_two_tokens_pct']:.2f}%), "
                  f"working_set={working_set_bytes()/1024**3:.3f} GiB", flush=True)
            assert_limits(started, args.max_minutes, args.max_working_set_gib)

        for target in (2, 3):
            source_table = result["pairs"][1]["table"]
            target_table = result["pairs"][target]["table"]
            pair_rows, shared_pairs = connection.execute(
                f"SELECT COALESCE(SUM(CAST(source.df AS REAL) * target.df), 0), COUNT(*) "
                f"FROM {source_table} AS source JOIN {target_table} AS target "
                "ON source.pair_key = target.pair_key"
            ).fetchone()
            result["pairs"][target]["estimated_join_rows"] = int(round(pair_rows))
            result["pairs"][target]["shared_pairs"] = int(shared_pairs)
            print(f"[pair join estimate] S1 x S{target}: shared_pairs={shared_pairs:,}, "
                  f"estimated key-join rows={int(round(pair_rows)):,}; no record join run", flush=True)
            assert_limits(started, args.max_minutes, args.max_working_set_gib)
    finally:
        connection.close()
        if temporary_directory is not None:
            temporary_directory.cleanup()

    result["preflight_elapsed_seconds"] = time.perf_counter() - started
    result["preflight_peak_gib"] = peak_working_set_bytes() / 1024**3
    return result


def write_preflight_report(result: dict) -> None:
    lines = [
        "# Blocking Preflight — Single Tokens vs. Token Pairs\n\n",
        "This report contains key-frequency and estimated key-join row counts only. No record-level token join, candidate generation, phonetic join, or recall calculation was run. Estimates are raw join rows before candidate deduplication.\n\n",
        "## Trimmed frame memory estimate\n\n| Source | Rows | Columns | Sample rows | Estimated full-frame memory |\n|---|---:|---:|---:|---:|\n",
    ]
    for src in (1, 2, 3):
        frame = result["frames"][src]
        lines.append(f"| Train S{src} | {frame['rows']:,} | 6 | {frame['sample_rows']:,} | {frame['estimated_gib']:.3f} GiB |\n")
    lines.extend(["\nMemory estimate extrapolates deep pandas usage from the sample rows; token scans use the name/address fields.\n",
                  f"\n## Aggressive single-token filtering (>{result['max_df']:.3%} document frequency)\n\n",
                  "Tokens are removed independently per source when their document frequency is greater than the threshold.\n\n",
                  "| Source | Rows | DF cutoff | Original vocabulary | Dropped tokens | Remaining vocabulary | Remaining postings | Remaining max DF | Median remaining DF |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"])
    for src in (1, 2, 3):
        stats = result["tokens"][src]
        lines.append(f"| Train S{src} | {stats['rows']:,} | {stats['threshold_records']:,} | {stats['unique_tokens']:,} | {stats['dropped_tokens']:,} | {stats['remaining_tokens']:,} | {stats['remaining_postings']:,} | {stats['remaining_max_df']:,} | {stats['remaining_median_df']:.0f} |\n")
    lines.extend(["\n### Document-frequency distribution before filtering\n\nPercentages use the source's distinct-token vocabulary as the denominator.\n\n| Source | DF=1 | DF 2-5 | DF 6-20 | DF 21-100 | DF >100 |\n|---|---:|---:|---:|---:|---:|\n"])
    for src in (1, 2, 3):
        stats = result["tokens"][src]
        total = stats["unique_tokens"] or 1
        buckets = stats["df_distribution"]
        percentages = [100 * buckets[key] / total for key in ("1", "2-5", "6-20", "21-100", "100+")]
        lines.append(f"| Train S{src} | {percentages[0]:.2f}% ({buckets['1']:,}) | {percentages[1]:.2f}% ({buckets['2-5']:,}) | {percentages[2]:.2f}% ({buckets['6-20']:,}) | {percentages[3]:.2f}% ({buckets['21-100']:,}) | {percentages[4]:.2f}% ({buckets['100+']:,}) |\n")
    lines.extend(["\n## Estimated join rows by approach (not executed)\n\n| Record pair | Aggressive single-token key join | Token-pair key join |\n|---|---:|---:|\n"])
    for src in (2, 3):
        token_stats = result["tokens"][src]
        pair_stats = result["pairs"][src]
        lines.append(f"| S1 × S{src} | {token_stats['estimated_join_rows']:,} | {pair_stats['estimated_join_rows']:,} |\n")
    lines.extend(["\nSingle-token estimate is the sum of DF(S1, token) × DF(target, token) over keys retained in both sources. Token-pair estimate uses unordered pairs from each record's 20 rarest retained tokens (rarity ordered by source-specific token DF, then token text), and sums pair-key document-frequency products. A record pair sharing multiple keys contributes multiple raw join rows; actual candidate deduplication has not been run.\n\n",
                  "### Records unable to emit a token pair\n\nThese records have fewer than two tokens remaining after the frequency filter and therefore cannot match through token-pair blocking. They require another blocker, such as phonetic matching. This is a minimum fallback count; records with two or more tokens can still have no matching pair in the other source.\n\n| Source | Records | Fewer than 2 retained tokens | Percentage |\n|---|---:|---:|---:|\n"])
    for src in (1, 2, 3):
        stats = result["pairs"][src]
        lines.append(f"| Train S{src} | {stats['rows']:,} | {stats['fewer_than_two_tokens']:,} | {stats['fewer_than_two_tokens_pct']:.2f}% |\n")
    lines.extend([
                  "\n",
                  "### Token-pair key counts\n\n| Source | Unique pair keys | Pair postings | Maximum pair DF | Shared pair keys with S1 |\n|---|---:|---:|---:|---:|\n"])
    for src in (1, 2, 3):
        stats = result["pairs"][src]
        shared = "—" if src == 1 else f"{stats['shared_pairs']:,}"
        lines.append(f"| Train S{src} | {stats['unique_pairs']:,} | {stats['pair_postings']:,} | {stats['max_pair_df']:,} | {shared} |\n")
    lines.extend([
        "\n## Resource status\n\n",
        f"- Preflight elapsed: {result['preflight_elapsed_seconds']:.1f}s.\n",
        f"- Measured peak process working set: {result['preflight_peak_gib']:.3f} GiB.\n",
        "- Pair-key frequencies were aggregated in a temporary disk-backed SQLite database, removed after the estimates were calculated.\n",
        "- No record-level join, candidate generation, phonetic join, or recall measurement was run.\n",
        "- Use these estimates to compare the two approaches before deciding whether to implement either candidate-generation path.\n",
    ])
    (ROOT / "blocking_preflight_report.md").write_text("".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-df", type=float, default=0.0005)
    parser.add_argument("--max-candidates", type=int, default=30)
    parser.add_argument("--chunk-rows", type=int, default=50_000)
    parser.add_argument("--memory-sample-rows", type=int, default=50_000)
    parser.add_argument("--pair-progress-records", type=int, default=100_000)
    parser.add_argument("--resume-pair-db", type=Path,
                        help="Reuse a verified SQLite database containing pair_df_s1/s2/s3 tables")
    parser.add_argument("--max-minutes", type=float, default=30)
    parser.add_argument("--max-working-set-gib", type=float, default=5.5)
    parser.add_argument("--preflight-only", action="store_true", default=True)
    parser.add_argument("--coverage-only", action="store_true",
                        help="Add fewer-than-two-retained-token counts to an existing preflight report")
    args = parser.parse_args()
    if args.coverage_only:
        update_coverage_report(args.max_df, args.chunk_rows)
        return
    result = preflight(args)
    write_preflight_report(result)
    print(f"Preflight complete: report={ROOT/'blocking_preflight_report.md'}; "
          f"peak={result['preflight_peak_gib']:.3f} GiB; "
          "full joins intentionally not started pending memory-safety review.", flush=True)


if __name__ == "__main__":
    main()
