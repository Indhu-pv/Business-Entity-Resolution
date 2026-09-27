# Business Entity Resolution — Data Cleaning

## Project overview

This project prepares business records from three data sources for entity resolution. It reads the TSV files under `train/` and `test/`, keeps the original data columns, and adds normalized name, address, and phonetic features. The labeled training ground-truth file is copied to the clean output folder without normalization.

## Work completed so far

- Implemented reusable cleaning functions in `code/business_entity_resolution/src/cleaning.py`.
- Added a driver in `code/business_entity_resolution/src/run_cleaning.py` to process train and test source files, save cleaned TSVs, and create a data profile report.
- Added `verify_cleaning.py` for follow-up checks on cleaned outputs.
- Generated the cleaned outputs in `dataset/clean/` and the processing report in `data_profile_report.md`.

## Cleaning operations

For each source record, the cleaner preserves the original fields (`entity_id`, `business_name`, `business_address`, `country`) and adds:

- `is_garbled_name`: flags names with a high proportion of non-printable characters.
- `normalized_name`: lowercases names, changes `&` to `and`, removes punctuation, and collapses whitespace.
- `expanded_name`: expands configured legal-suffix abbreviations, such as `corp` and `pvt`.
- `stripped_core_name`: removes trailing legal suffixes from the expanded name.
- `metaphone_key` and `soundex_key`: phonetic keys derived from the core name.
- `normalized_address`: lowercases and expands configured address abbreviations, such as `rd` to `road`.
- `numeric_tokens`: extracts digit sequences from the original address.
- `address_text_core`: removes numeric tokens from the normalized address.

The output source files contain 13 columns: 4 original columns and 9 derived columns.

## Input and output files

Inputs:

- `train/train_source1.tsv`
- `train/train_source2.tsv`
- `train/train_source3.tsv`
- `train/train_ground_truth.tsv`
- `test/test_source1.tsv`
- `test/test_source2.tsv`
- `test/test_source3.tsv`

Generated outputs:

- `dataset/clean/train_source1_clean.tsv`
- `dataset/clean/train_source2_clean.tsv`
- `dataset/clean/train_source3_clean.tsv`
- `dataset/clean/train_ground_truth_clean.tsv`
- `dataset/clean/test_source1_clean.tsv`
- `dataset/clean/test_source2_clean.tsv`
- `dataset/clean/test_source3_clean.tsv`

## Run the cleaning pipeline

Open PowerShell in the project root, then run:

```powershell
python -m pip install -r requirements.txt
python -u code\business_entity_resolution\src\run_cleaning.py
```

The pipeline writes the cleaned TSV files to `dataset/clean/` and refreshes `data_profile_report.md`.

## Verify the cleaned files

After the cleaning pipeline finishes, run:

```powershell
python verify_cleaning.py
```

The verifier checks for expected files and columns, reports null/empty values in derived fields, samples cleaned records, spot-checks suffix expansion and phonetic keys, and counts duplicate entity IDs. A nonzero exit code means the check did not finish cleanly; review its terminal output for missing files, missing columns, or a runtime error. The verifier does not prove every normalization is semantically correct, so sampled records should also be reviewed.

## Results recorded in the current profile report

The existing `data_profile_report.md` records that all six source datasets were processed and saved with 13 columns each. It also records:

- No duplicate entity IDs or bad source-ID prefixes in the six source inputs.
- No garbled names detected by the configured check.
- Some missing raw business names and addresses in source 2/source 3, which remain empty in corresponding normalized fields.
- A small number of empty core names after removing legal suffixes; inspect those cases if they matter to downstream matching.
- France appears in the test data but not in the training data, so it is a previously unseen test country.

These are the pipeline's recorded checks and observations, not a guarantee that all records are correct for every matching use case. In particular, abbreviation maps and punctuation handling may need refinement for your dataset's languages and address conventions.

## Dependencies

Dependencies and pinned versions are listed in `requirements.txt`: pandas, rapidfuzz, jellyfish, and scikit-learn.

## Project Stages and Current Status

This section records what is complete, where work stopped, and what remains. Status is based on the generated files and reports currently in this workspace; a script being present does not by itself mean that its checks or pipeline completed successfully.

| Stage | Status | Evidence / outcome |
|---|---|---|
| 1. Inspect and profile input data | Complete | `data_profile_report.md` records row counts, nulls, duplicate IDs, source prefixes, country distributions, and ground-truth match counts. |
| 2. Clean and normalize train/test sources | Outputs generated | All six cleaned source TSVs and the copied clean ground-truth TSV are present under `dataset/clean/`; each source has 13 columns. The report records normalization samples and data-quality observations. |
| 3. Verify cleaning outputs | Verification available; pass not recorded | `verify_cleaning.py` is present, but there is no saved verification result confirming that it completed successfully. Run it to formally check the current outputs. |
| 4. Blocking preflight / candidate generation | Preflight complete; candidate generation pending | The 0.05% single-token estimate and token-pair estimate are recorded in `blocking_preflight_report.md`. No record-level join or candidate output has been generated. |
| 5. Build and evaluate a matching model | Not started | No candidate-based feature/model training or evaluation results are recorded. |
| 6. Generate test predictions / final deliverables | Not started | Test data has been cleaned, but test candidate generation, inference, and final prediction output are not implemented or recorded. |

### Blocking: Error and Stop Point

The earlier full-vocabulary TF-IDF attempt exceeded the configured memory safety limit. A subsequent hashing-based run successfully fitted IDF weights on a 150,000-row sample and built the 5,034,616-row train S2 sparse matrix, but exceeded the 5.5 GiB working-set limit during the first sparse candidate-query operation. The recorded peak was **5.785 GiB** after approximately **14 minutes 50 seconds**. The process was stopped by the safety guard; this was a resource-limit stop, not a completed blocking run. The query batch did not finish, so no candidates or recall metrics were produced. Train S3 and test sources were not processed. See [`blocking_report.md`](blocking_report.md) for the recorded measurements.

**Was the error completely solved? No.** The earlier hashing-based sparse candidate-query attempt exceeded the 5.5 GiB memory limit. The newer estimate-only preflight completed in about 14m52s under a **30-minute wall-clock guard**, with a measured peak working set of 0.361 GiB. The blocking driver now defaults to that 30-minute limit. At the 0.05% document-frequency cutoff, the estimated single-token key joins remain too large (3,009,669,539 rows for S1×S2 and 2,998,403,527 for S1×S3). The capped token-pair estimates are much smaller (54,767,047 and 48,873,986 raw key-join rows respectively), but are estimates, not executed record joins or measured candidate counts. See [`blocking_preflight_report.md`](blocking_preflight_report.md) for the full frequency distribution and methodology.

Token-pair blocking alone cannot emit a pair for records with fewer than two retained tokens: 591,345 S1 records (26.80%), 1,151,619 S2 records (22.87%), and 1,343,588 S3 records (25.42%). These records need another candidate channel such as phonetic blocking. This is a minimum fallback population; records with two or more retained tokens may also have no shared pair in the opposite source. The current [`run_blocking.py`](code/business_entity_resolution/src/run_blocking.py) computes these estimates and counts only; it does not execute record-level token or phonetic joins, produce candidates, or measure recall.

**Current stopping point:** data cleaning and the estimate-only blocking preflight are complete. The next decision is to implement token-pair blocking together with a phonetic fallback, then measure candidate recall against ground truth. The process currently stops before any candidate pairs are generated.

### Pending Work

1. Run `python verify_cleaning.py` and resolve any failed checks; review the reported empty/missing name or address values as needed.
2. Implement and test memory-bounded train token-pair blocking for S1-to-S2 and S1-to-S3, alongside phonetic fallback for all records, especially those with fewer than two retained tokens.
3. Measure candidate recall against `train_ground_truth_clean.tsv`, inspect missed matches, and tune candidate limits and blocking rules.
4. Once train blocking is reliable and within resource limits, generate test candidates, implement match scoring/model training, evaluate it, and produce the final test predictions.

### Scale and Memory Context

The six source files contain over 20 million records: Train S1 2,206,821, S2 5,034,616, S3 5,285,603; Test S1 1,732,544, S2 4,887,273, S3 5,082,316. The earlier report estimates full-file pandas memory for selected columns at about 1.91, 4.56, 4.73, 1.53, 4.56, and 4.64 GiB respectively. These estimates explain why candidate generation must bound intermediate data; they are not measurements of the current preflight's memory use. The train-only hashing attempt's measured figures are documented in `blocking_report.md`.
