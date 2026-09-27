# Blocking Run Report — Stopped at Memory Guard

## Outcome

The train-only run was stopped by the 5.5 GiB working-set safety policy after the measured process peak reached **5.785 GiB**. It had run for approximately **14 minutes 50 seconds** (started at 20:48:15, stopped at 21:03:06). System available RAM at the stop check was about **0.49 GiB** and recovered to about **6.7 GiB** after the process exited.

This is a failed/incomplete run report, not a blocking-quality result. No test records were processed, and there is no candidate recall figure.

## Dataset scale

| Clean source | Exact rows | Estimated full pandas memory |
|---|---:|---:|
| Train S1 | 2,206,821 | 1.906 GiB |
| Train S2 | 5,034,616 | 4.560 GiB |
| Train S3 | 5,285,603 | 4.725 GiB |
| Test S1 | 1,732,544 | 1.526 GiB |
| Test S2 | 4,887,273 | 4.562 GiB |
| Test S3 | 5,082,316 | 4.637 GiB |

Memory estimates are deep pandas usage extrapolated from 50,000-row chunks of the selected string columns; they are not full-file resident measurements. Test figures are included for scale only; no test files were read during this run.

## Hashing and sampled IDF

- Fixed HashingVectorizer width: **1,048,576 features** (`2**20`); no fitted vocabulary dictionary exists to report.
- Active hash bins in the IDF sample: **258,331**.
- Sampled rows: **50,000 from each of S1, S2, S3; 150,000 total**.
- Word tokens (length at least 3) and character 4-grams were combined in one analyzer, distinguished by `w:` and `c:` prefixes.
- `alternate_sign=False`; IDF was fitted with `TfidfTransformer` on the sample. Sample transform/IDF fit took **8.2 seconds** and used **0.137 GiB** working set.
- The initial full Count/TfidfVectorizer fit had separately been stopped after 22:44 at a measured 6.73 GiB working set; this run used hashing as requested.

## Sparse matrix reached before stop

The train S2 target matrix completed successfully:

- Rows: **5,034,616**
- Nonzeros: **339,686,651**
- Sparse CSR payload estimate: **2.568 GiB** (float32 values, int32 indices, int64 row pointers)
- The S2 compact phonetic ID array was written. The process stopped before the driver emitted posting-cardinality/runtime summaries.
- S3 was not processed.

The process working-set high-water mark was measured from Windows process counters. It rose from about 2.99 GiB after S2 CSR construction to 5.785 GiB during the subsequent candidate-query phase. The S2 per-S1 intermediate remained 0 bytes, indicating that no query batch completed and no candidate rows were emitted. The memory spike is consistent with the first chunked sparse product materializing too many nonzero similarities despite sparse input storage.

## Recall and candidate metrics

| Metric | Result |
|---|---|
| TF-IDF blocker recall | Not measured; query did not complete |
| Phonetic blocker recall | Not measured |
| Union pair-level recall | Not measured |
| Average candidate-set size | Not measured |
| Country breakdown | Not measured |
| Missed-pair examples | Not available |
| Train candidate output | Not generated; only an empty intermediate file exists |
| Test candidates | Not run |

## Runtime and memory

- Elapsed train-only attempt: approximately **14m 50s**.
- Measured full-process peak working set: **5.785 GiB**; the process was force-stopped immediately after detection.
- Post-stop available RAM: approximately **6.7 GiB**.
- No feature/model training was attempted.

## Stop point

No further blocker variant, chunk-size reduction, sampling fallback, or test run was attempted. The sparse similarity stage needs a more memory-bounded top-K strategy (for example, feature-posting accumulation that prunes per candidate row, or a much smaller query batch with measured guards) before it can safely produce full-train recall. The existing temporary S2 CSR/memmap artifacts and zero-byte intermediate are retained under `dataset/clean/.blocking_tmp/` for inspection; they are not candidate outputs.
