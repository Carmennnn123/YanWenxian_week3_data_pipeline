# Data Cleaning and Validation Pipeline

Pipeline for scraped article data: load JSON → clean (text, dates, incomplete, dedup) → validate → write **cleaned_output.json** and **quality_report.txt**.

**Requirements:** Python 3.8+, pandas, python-dateutil → `pip install pandas python-dateutil` (or `py -m pip install ...` on Windows).

**Run:** From project directory: `python cleaner.py` or `py -m cleaner`. Uses `sample_data.json` by default; override with `run_cleaning_pipeline(input_path=..., output_path=..., report_path=...)`.

**Input:** JSON as a top-level array of article objects, or `{"articles": [...]}`.

---

### Project structure

| File | Purpose |
|------|---------|
| **cleaner.py** | Cleaning logic + full pipeline entry point. |
| **validator.py** | `validate_row()` and rules; `batch_validate()`, `ValidationStatistics`. |
| **sample_data.json** | Sample input (default). |
| **cleaned_output.json** | *Generated.* Valid records only (JSON array). |
| **quality_report.txt** | *Generated.* Record stats, completeness, validation, failures, date range, duplicates. |
| **prompt-log.md** | AI-assisted development log. |

---

### Cleaning steps (in order)

1. **Text** — HTML decode (`&amp;`, `&nbsp;`, etc.), collapse `\s+`, strip; applied to title, content, author, source, url.  
2. **Dates** — Parse `published` / `published_date` to ISO `YYYY-MM-DDTHH:MM:SSZ`; invalid → null.  
3. **Incomplete** — Drop rows missing title, content, or url (empty/None/whitespace).  
4. **Deduplication** — By normalized title + url; keep first.

### Validation rules (`validator.py`)

A row **passes** only if all apply: **title** non-empty; **content** ≥ 120 chars; **url** starts with `http://` or `https://`; **published** (or `published_date`) present. Failures get a reason code (`missing_title`, `short_content`, `invalid_url`, `missing_published`) and are listed in the quality report.

### Outputs

- **cleaned_output.json** — JSON array of records that passed cleaning and validation; text normalized, dates in ISO.  
- **quality_report.txt** — Record counts (original/cleaned/deleted), field completeness %, validation pass/fail and pass rate, failure distribution, date range, duplicate stats, failed-record details.

### Customization

- **Paths:** Pass `input_path`, `output_path`, `report_path` to `run_cleaning_pipeline()`.  
- **Validation:** Edit `validate_row()` in `validator.py` (add/remove checks, change `MIN_CONTENT_LENGTH`); update `REASON_LABELS` for report text.  
- **Cleaning:** Add steps in `run_cleaning_pipeline()` in the cleaning block; extend `generate_quality_report()` if you need extra metrics.
