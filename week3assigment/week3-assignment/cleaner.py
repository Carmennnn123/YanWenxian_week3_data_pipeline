"""
Data cleaning implementation for scraped article data.
Normalizes text, dates; removes incomplete records and duplicates.
Includes full pipeline: load -> clean -> validate -> save outputs and report.
"""

import html
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from dateutil import parser as dateutil_parser

from validator import REASON_LABELS, ValidationStatistics, batch_validate


# Regex for merging multiple whitespace
WHITESPACE_PATTERN = re.compile(r"\s+")


def clean_text_series(series: pd.Series) -> pd.Series:
    """
    Clean text: remove extra whitespace and HTML artifacts (decode entities via html.unescape),
    normalize text encoding to Unicode, merge multiple spaces (\\s+), strip leading/trailing whitespace.
    Handles: empty Series, None/NaN, non-string types, empty string after strip.
    """
    if series.empty:
        return series.copy()

    def _clean(value: Any) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        try:
            s = str(value) if not isinstance(value, (dict, list)) else ""
        except Exception:
            return ""
        if not s:
            return ""
        try:
            decoded = html.unescape(s)
        except Exception:
            decoded = s
        merged = WHITESPACE_PATTERN.sub(" ", decoded)
        return merged.strip()

    return series.apply(_clean)


def parse_iso_date(value: Any) -> str | None:
    """
    Parse date with dateutil.parser; return ISO format string (YYYY-MM-DDTHH:MM:SSZ) or None if invalid.
    Handles: None, NaN, empty string, invalid format, non-scalar (list/dict), parser errors.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (dict, list)):
        return None
    try:
        s = str(value).strip()
    except Exception:
        return None
    if not s or s.lower() in ("none", "null", "nan"):
        return None
    try:
        dt = dateutil_parser.parse(s)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError, KeyError):
        return None


def _is_missing(val: Any) -> bool:
    """True if value is missing: None, NaN, empty string, or whitespace only."""
    if val is None:
        return True
    if isinstance(val, float) and pd.isna(val):
        return True
    try:
        return not str(val).strip()
    except Exception:
        return True


def drop_incomplete_records(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop records missing title, content, or url.
    Missing = empty string, None, or whitespace only.
    Handles: empty DataFrame, missing required columns (drops nothing for that column).
    """
    if df.empty:
        return df.copy()
    required = ["title", "content", "url"]
    out = df
    for col in required:
        if col not in out.columns:
            continue
        try:
            mask = out[col].apply(_is_missing)
            out = out.loc[~mask]
        except Exception:
            continue
    return out.reset_index(drop=True)


def deduplicate_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Deduplicate by normalized title and url; keep first occurrence.
    Handles: empty DataFrame; missing title or url column (returns copy unchanged).
    """
    if df.empty:
        return df.copy()
    if "title" not in df.columns or "url" not in df.columns:
        return df.reset_index(drop=True)
    try:
        title_norm = clean_text_series(df["title"].astype(str))
        url_norm = clean_text_series(df["url"].astype(str))
    except Exception:
        return df.reset_index(drop=True)
    key = pd.DataFrame({"title_norm": title_norm, "url_norm": url_norm})
    return df.loc[~key.duplicated(keep="first")].reset_index(drop=True)


def load_data(path: str | Path) -> pd.DataFrame:
    """
    Load JSON file into a pandas DataFrame.
    Supports: list of objects, {\"articles\": [...]}, single object, null/empty.
    Handles: empty list, empty articles, null data, non-list/dict (wraps in list).
    """
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data is None:
        return pd.DataFrame()
    if isinstance(data, list):
        return pd.DataFrame(data) if data else pd.DataFrame()
    if isinstance(data, dict) and "articles" in data:
        articles = data["articles"]
        if isinstance(articles, list):
            return pd.DataFrame(articles) if articles else pd.DataFrame()
    if isinstance(data, dict):
        return pd.DataFrame([data])
    return pd.DataFrame()


def save_clean_data(df: pd.DataFrame, path: str | Path) -> None:
    """
    Save cleaned DataFrame to JSON (records orientation).
    Handles: empty DataFrame; creates parent directory if missing.
    """
    path = Path(path)
    if path.parent != path:
        path.parent.mkdir(parents=True, exist_ok=True)
    df.to_json(path, orient="records", indent=2, force_ascii=False)


def generate_quality_report(
    original_count: int,
    cleaned_count: int,
    deleted_incomplete: int,
    deleted_duplicates: int,
    df_cleaned: pd.DataFrame,
    stats: ValidationStatistics,
    include_failed_details: bool = True,
) -> str:
    """
    Generate quality_report.txt with: record stats, field completeness,
    validation stats, failure distribution, date range, duplicate stats.
    """
    lines = []

    # --- Requirements checklist (per specification) ---
    lines.append("QUALITY REPORT")
    lines.append("=" * 60)
    lines.append("")
    lines.append("REQUIREMENTS CHECKLIST")
    lines.append("-" * 60)
    lines.append("  [1] Data Cleaning: whitespace/HTML removal, text encoding, ISO dates, special chars")
    lines.append("  [2] Data Validation: required fields (title, content, url), URL format, content length, reasons")
    lines.append("  [3] Quality Report: total processed, valid vs invalid, completeness %, common failures")
    lines.append("")
    lines.append("1. RECORD PROCESSING STATISTICS")
    lines.append("-" * 60)
    total_deleted = deleted_incomplete + deleted_duplicates
    lines.append(f"  Total records processed:   {original_count}")
    lines.append(f"  Cleaned record count:      {cleaned_count}")
    lines.append(f"  Deleted record count:      {total_deleted}")
    lines.append(f"    - Missing (incomplete):  {deleted_incomplete}")
    lines.append(f"    - Duplicates:            {deleted_duplicates}")
    lines.append("")

    # --- 2. Field completeness (non-null ratio %) ---
    lines.append("2. FIELD COMPLETENESS (non-null ratio %)")
    lines.append("-" * 60)
    n = len(df_cleaned)
    for col in df_cleaned.columns:
        non_null = df_cleaned[col].notna().sum()
        # Treat empty string as missing for completeness
        non_empty = (df_cleaned[col].astype(str).str.strip() != "").sum()
        pct = (non_empty / n * 100) if n else 0
        lines.append(f"  {col:<25} {pct:6.1f}%  ({non_empty}/{n})")
    lines.append("")

    # --- 3. Validation result statistics ---
    lines.append("3. VALIDATION RESULT STATISTICS")
    lines.append("-" * 60)
    total = stats.total
    passed = stats.passed
    failed = stats.failed
    pass_rate = (passed / total * 100) if total else 0
    lines.append(f"  Total validation passed:   {passed}")
    lines.append(f"  Total validation failed:   {failed}")
    lines.append(f"  Pass rate:                 {pass_rate:.1f}%")
    lines.append("")

    # --- 4. Validation failure distribution ---
    lines.append("4. VALIDATION FAILURE DISTRIBUTION")
    lines.append("-" * 60)
    if stats.failure_reasons:
        for reason, count in stats.failure_reasons.most_common():
            lines.append(f"  {count:4d}  {REASON_LABELS.get(reason, reason)}")
    else:
        lines.append("  (none)")
    lines.append("")

    # --- 5. Date coverage range ---
    lines.append("5. DATE COVERAGE RANGE (publication date)")
    lines.append("-" * 60)
    date_col = "published_date" if "published_date" in df_cleaned.columns else "published"
    if date_col in df_cleaned.columns:
        ser = pd.to_datetime(df_cleaned[date_col], errors="coerce")
        valid_dates = ser.dropna()
        if len(valid_dates) > 0:
            earliest = valid_dates.min()
            latest = valid_dates.max()
            lines.append(f"  Earliest:  {earliest}")
            lines.append(f"  Latest:    {latest}")
            lines.append(f"  Records with date: {len(valid_dates)}/{n}")
        else:
            lines.append("  No valid dates found.")
    else:
        lines.append("  No date column present.")
    lines.append("")

    # --- 6. Duplicate record statistics ---
    lines.append("6. DUPLICATE RECORD STATISTICS")
    lines.append("-" * 60)
    lines.append(f"  Original duplicate count:  {deleted_duplicates} (before dedup)")
    lines.append(f"  Deleted duplicate count:   {deleted_duplicates}")
    lines.append("")

    # --- Failed record details (from validator report) ---
    if include_failed_details and stats.failed_record_details:
        lines.append("FAILED RECORD DETAILS")
        lines.append("-" * 60)
        for detail in stats.failed_record_details:
            lines.append(f"  Index:  {detail['index']}")
            lines.append(f"  Reason: {detail.get('message', detail.get('reason', 'Unknown'))}")
            lines.append("")

    # --- Insightful metrics summary ---
    retention_pct = (cleaned_count / original_count * 100) if original_count else 0
    valid_pct = (stats.passed / original_count * 100) if original_count else 0
    top_failure = stats.failure_reasons.most_common(1)[0] if stats.failure_reasons else (None, 0)
    top_failure_label = REASON_LABELS.get(top_failure[0], top_failure[0]) if top_failure[0] else ""
    lines.append("INSIGHTFUL METRICS SUMMARY")
    lines.append("-" * 60)
    lines.append(f"  End-to-end retention:  {valid_pct:.1f}% ({stats.passed}/{original_count} records saved)")
    lines.append(f"  Cleaning retention:    {retention_pct:.1f}% ({cleaned_count}/{original_count} after cleaning)")
    lines.append(f"  Validation pass rate: {pass_rate:.1f}% (on cleaned set)")
    if top_failure_label:
        lines.append(f"  Top failure reason:     {top_failure_label} (n={top_failure[1]})")
    lines.append("")
    lines.append("DOCUMENTED PROCESS")
    lines.append("-" * 60)
    lines.append("  This report is generated by the data cleaning and validation pipeline.")
    lines.append("  For AI-assisted development process and historical metrics, see prompt-log.md.")
    lines.append("")
    lines.append("=" * 60)
    lines.append("End of report")
    return "\n".join(lines)


def run_cleaning_pipeline(
    input_path: str | Path = "sample_data.json",
    output_path: str | Path = "cleaned_output.json",
    report_path: str | Path = "quality_report.txt",
) -> pd.DataFrame:
    """
    Full data processing pipeline: load -> clean -> validate -> save cleaned data and quality report.
    Prints progress and statistics for each step. Returns the cleaned DataFrame (all records after cleaning).
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    report_path = Path(report_path)

    print("=" * 60)
    print("DATA PROCESSING PIPELINE")
    print("=" * 60)

    # --- 1. Load raw data ---
    print("\n[1/6] LOAD RAW DATA")
    print("-" * 40)
    df = load_data(input_path)
    n_load = len(df)
    print(f"  Input file:     {input_path}")
    print(f"  Records loaded: {n_load}")
    print(f"  Columns:        {list(df.columns)}")

    # Normalize "published" -> "published_date" if present
    if "published" in df.columns and "published_date" not in df.columns:
        df["published_date"] = df["published"]

    # --- 2a. Text cleaning ---
    print("\n[2/6] CLEANING STEPS")
    print("-" * 40)
    text_cols = [c for c in ["title", "content", "author", "source", "url"] if c in df.columns]
    for col in text_cols:
        df[col] = clean_text_series(df[col].astype(str))
    print(f"  Text cleaning:  applied to {text_cols}")

    # --- 2b. Date standardization ---
    if "published_date" in df.columns:
        before_dates = df["published_date"].copy()
        df["published_date"] = df["published_date"].apply(parse_iso_date)
        n_parsed = df["published_date"].notna().sum()
        n_invalid = before_dates.notna().sum() - n_parsed
        print(f"  Date standard:  parsed to ISO; valid={n_parsed}, invalid/missing={n_invalid}")
    else:
        print("  Date standard:  (no published_date column)")

    # --- 2c. Delete incomplete records ---
    n_before_drop = len(df)
    df = drop_incomplete_records(df)
    n_after_drop = len(df)
    n_dropped = n_before_drop - n_after_drop
    print(f"  Incomplete:     removed {n_dropped} records (missing title/content/url); {n_after_drop} remaining")

    # --- 2d. Deduplication ---
    n_before_dedup = len(df)
    df = deduplicate_data(df)
    n_after_dedup = len(df)
    n_dupes = n_before_dedup - n_after_dedup
    print(f"  Deduplication:  removed {n_dupes} duplicates; {n_after_dedup} remaining")

    # --- 3. Apply validation rules ---
    print("\n[3/6] VALIDATION")
    print("-" * 40)
    stats, failed_details = batch_validate(df)
    print(f"  Total records:  {stats.total}")
    print(f"  Passed:         {stats.passed}")
    print(f"  Failed:         {stats.failed}")
    if stats.failure_reasons:
        print("  Failure reasons:")
        for reason, count in stats.failure_reasons.most_common():
            print(f"    - {count}x {REASON_LABELS.get(reason, reason)}")

    # --- 4 & 5. Generate cleaned data (valid only) and quality report ---
    print("\n[4/6] GENERATE CLEANED DATA")
    print("-" * 40)
    failed_indices = {f["index"] for f in failed_details}
    passed_indices = [i for i in df.index if i not in failed_indices]
    df_valid = df.loc[passed_indices].reset_index(drop=True)
    print(f"  Valid records to save: {len(df_valid)}")

    print("\n[5/6] GENERATE QUALITY REPORT")
    print("-" * 40)
    report_text = generate_quality_report(
        original_count=n_load,
        cleaned_count=n_after_dedup,
        deleted_incomplete=n_dropped,
        deleted_duplicates=n_dupes,
        df_cleaned=df,
        stats=stats,
        include_failed_details=True,
    )
    print(f"  Report length:  {len(report_text)} chars")

    # --- 6. Save all output files ---
    print("\n[6/6] SAVE OUTPUT FILES")
    print("-" * 40)
    save_clean_data(df_valid, output_path)
    print(f"  Cleaned data:   {output_path} ({len(df_valid)} records)")
    report_path.write_text(report_text, encoding="utf-8")
    print(f"  Quality report: {report_path}")

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  Summary: {n_load} loaded -> {n_after_dedup} after cleaning -> {len(df_valid)} valid (saved)")
    print()

    return df


if __name__ == "__main__":
    run_cleaning_pipeline()
