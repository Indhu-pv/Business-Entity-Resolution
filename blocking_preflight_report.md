# Blocking Preflight — Single Tokens vs. Token Pairs

This report contains key-frequency and estimated key-join row counts only. No record-level token join, candidate generation, phonetic join, or recall calculation was run. Estimates are raw join rows before candidate deduplication.

## Trimmed frame memory estimate

| Source | Rows | Columns | Sample rows | Estimated full-frame memory |
|---|---:|---:|---:|---:|
| Train S1 | 2,206,821 | 6 | 50,000 | 0.906 GiB |
| Train S2 | 5,034,616 | 6 | 50,000 | 2.238 GiB |
| Train S3 | 5,285,603 | 6 | 50,000 | 2.323 GiB |

Memory estimate extrapolates deep pandas usage from the sample rows; token scans use the name/address fields.

## Aggressive single-token filtering (>0.050% document frequency)

Tokens are removed independently per source when their document frequency is greater than the threshold.

| Source | Rows | DF cutoff | Original vocabulary | Dropped tokens | Remaining vocabulary | Remaining postings | Remaining max DF | Median remaining DF |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Train S1 | 2,206,821 | 1,103 | 454,364 | 1,632 | 452,732 | 5,486,943 | 1,103 | 1 |
| Train S2 | 5,034,616 | 2,517 | 1,274,754 | 1,492 | 1,273,262 | 13,213,681 | 2,513 | 1 |
| Train S3 | 5,285,603 | 2,642 | 1,300,237 | 1,511 | 1,298,726 | 13,340,141 | 2,640 | 1 |

### Document-frequency distribution before filtering

Percentages use the source's distinct-token vocabulary as the denominator.

| Source | DF=1 | DF 2-5 | DF 6-20 | DF 21-100 | DF >100 |
|---|---:|---:|---:|---:|---:|
| Train S1 | 53.99% (245,333) | 25.59% (116,280) | 11.58% (52,614) | 6.28% (28,513) | 2.56% (11,624) |
| Train S2 | 62.69% (799,191) | 23.21% (295,853) | 8.38% (106,882) | 4.04% (51,451) | 1.68% (21,377) |
| Train S3 | 63.48% (825,332) | 22.95% (298,438) | 7.91% (102,881) | 4.02% (52,334) | 1.63% (21,252) |

## Estimated join rows by approach (not executed)

| Record pair | Aggressive single-token key join | Token-pair key join |
|---|---:|---:|
| S1 × S2 | 3,009,669,539 | 54,767,047 |
| S1 × S3 | 2,998,403,527 | 48,873,986 |

Single-token estimate is the sum of DF(S1, token) × DF(target, token) over keys retained in both sources. Token-pair estimate uses unordered pairs from each record's 20 rarest retained tokens (rarity ordered by source-specific token DF, then token text), and sums pair-key document-frequency products. A record pair sharing multiple keys contributes multiple raw join rows; actual candidate deduplication has not been run.

### Records unable to emit a token pair

These records have fewer than two tokens remaining after the frequency filter and therefore cannot match through token-pair blocking. They require another blocker, such as phonetic matching. This is a minimum fallback count; records with two or more tokens can still have no matching pair in the other source.

| Source | Records | Fewer than 2 retained tokens | Percentage |
|---|---:|---:|---:|
| Train S1 | 2,206,821 | 591,345 | 26.80% |
| Train S2 | 5,034,616 | 1,151,619 | 22.87% |
| Train S3 | 5,285,603 | 1,343,588 | 25.42% |

### Token-pair key counts

| Source | Unique pair keys | Pair postings | Maximum pair DF | Shared pair keys with S1 |
|---|---:|---:|---:|---:|
| Train S1 | 5,295,160 | 6,506,944 | 928 | — |
| Train S2 | 8,979,334 | 16,451,141 | 2,023 | 4,482,699 |
| Train S3 | 8,359,256 | 14,040,454 | 1,868 | 4,030,238 |

## Resource status

- Preflight elapsed: 892.0s.
- Measured peak process working set: 0.361 GiB.
- Pair-key frequencies were aggregated in a temporary disk-backed SQLite database, removed after the estimates were calculated.
- No record-level join, candidate generation, phonetic join, or recall measurement was run.
- Use these estimates to compare the two approaches before deciding whether to implement either candidate-generation path.
