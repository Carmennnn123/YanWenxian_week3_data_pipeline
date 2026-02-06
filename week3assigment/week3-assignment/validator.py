"""
Validation implementation for scraped article data.
Comprehensive validation with clear, contextual error messages.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TypedDict

import pandas as pd


MIN_CONTENT_LENGTH = 120
MAX_TITLE_LENGTH = 500
MAX_CONTENT_LENGTH = 1_000_000
URL_PREFIX_PATTERN = re.compile(r"^https?://.+", re.IGNORECASE)


class ValidationResult(TypedDict):
    passed: bool
    reason: str | None
    message: str | None


def _is_empty(value: object) -> bool:
    """True if value is None, NaN, empty string, or whitespace only."""
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    try:
        return not str(value).strip()
    except Exception:
        return True


def _safe_str(value: object, default: str = "") -> str:
    """Convert to string safely; return default for non-string-like or on error."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    try:
        return str(value).strip() if not isinstance(value, (dict, list)) else default
    except Exception:
        return default


def validate_row(row: pd.Series) -> ValidationResult:
    """
    Run all validation checks on one row.
    Returns passed, first reason code (for grouping), and a clear message listing all failures.
    """
    errors: list[str] = []

    # --- Title ---
    title = _safe_str(row.get("title"))
    if not title:
        errors.append("Title is missing or empty.")
    elif len(title) > MAX_TITLE_LENGTH:
        errors.append(f"Title is too long: {len(title)} characters (maximum {MAX_TITLE_LENGTH}).")

    # --- Content ---
    content = _safe_str(row.get("content"))
    if not content:
        errors.append("Content is missing or empty.")
    elif len(content) < MIN_CONTENT_LENGTH:
        errors.append(
            f"Content is too short: {len(content)} characters (minimum {MIN_CONTENT_LENGTH} required)."
        )
    elif len(content) > MAX_CONTENT_LENGTH:
        errors.append(
            f"Content is too long: {len(content)} characters (maximum {MAX_CONTENT_LENGTH})."
        )

    # --- URL ---
    url = _safe_str(row.get("url"))
    if not url:
        errors.append("URL is missing or empty.")
    elif not url.startswith(("http://", "https://")):
        errors.append(
            f"URL must start with http:// or https:// (got: {url[:50]}{'...' if len(url) > 50 else ''})."
        )
    elif not URL_PREFIX_PATTERN.match(url):
        errors.append("URL has invalid format after scheme (expected a host/path).")

    # --- Published date ---
    published = row.get("published_date") or row.get("published")
    if _is_empty(published):
        errors.append("Published date is missing or empty.")

    # --- Result ---
    if not errors:
        return {"passed": True, "reason": None, "message": None}
    message = " ".join(errors)
    reason = _error_to_reason_code(errors[0])
    return {"passed": False, "reason": reason, "message": message}


def _error_to_reason_code(first_error: str) -> str:
    """Map first error text to a reason code for grouping."""
    if "Title is missing" in first_error:
        return "missing_title"
    if "Title is too long" in first_error:
        return "title_too_long"
    if "Content is missing" in first_error:
        return "missing_content"
    if "Content is too short" in first_error:
        return "short_content"
    if "Content is too long" in first_error:
        return "content_too_long"
    if "URL is missing" in first_error:
        return "missing_url"
    if "URL must start with" in first_error or "URL has invalid format" in first_error:
        return "invalid_url"
    if "Published date is missing" in first_error:
        return "missing_published"
    return "validation_failed"


@dataclass
class ValidationStatistics:
    """Aggregate stats from batch validation."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    failure_reasons: Counter = field(default_factory=Counter)
    failed_record_details: list[dict] = field(default_factory=list)


# Human-readable labels for reason codes (used when message not available)
REASON_LABELS: dict[str, str] = {
    "missing_title": "Title is missing or empty.",
    "title_too_long": f"Title exceeds maximum length ({MAX_TITLE_LENGTH} characters).",
    "missing_content": "Content is missing or empty.",
    "short_content": f"Content is too short (minimum {MIN_CONTENT_LENGTH} characters).",
    "content_too_long": f"Content exceeds maximum length ({MAX_CONTENT_LENGTH} characters).",
    "missing_url": "URL is missing or empty.",
    "invalid_url": "URL must start with http:// or https:// and have valid format.",
    "missing_published": "Published date is missing or empty.",
    "validation_failed": "Validation failed.",
}


def batch_validate(df: pd.DataFrame) -> tuple[ValidationStatistics, list[dict]]:
    """
    Validate entire DataFrame.
    Returns (validation_statistics, failed_record_details).
    Each failed detail includes index, reason (code), message (clear text), and row.
    """
    stats = ValidationStatistics(total=len(df))
    for idx, row in df.iterrows():
        result = validate_row(row)
        if result["passed"]:
            stats.passed += 1
        else:
            stats.failed += 1
            reason = result["reason"] or "validation_failed"
            stats.failure_reasons[reason] += 1
            message = result.get("message") or REASON_LABELS.get(reason, reason)
            stats.failed_record_details.append({
                "index": int(idx) if isinstance(idx, (int, float)) else idx,
                "reason": reason,
                "message": message,
                "row": row.to_dict(),
            })
    return stats, stats.failed_record_details


def generate_validation_report(
    stats: ValidationStatistics,
    include_failed_details: bool = True,
) -> str:
    """Generate a validation result summary with clear failure descriptions."""
    lines = [
        "Validation Report",
        "=" * 50,
        f"Total records:  {stats.total}",
        f"Passed:        {stats.passed}",
        f"Failed:        {stats.failed}",
        "",
        "Failure reason distribution:",
        "-" * 50,
    ]
    if stats.failure_reasons:
        for reason, count in stats.failure_reasons.most_common():
            label = REASON_LABELS.get(reason, reason)
            lines.append(f"  {count:4d}  {label}")
    else:
        lines.append("  (none)")
    lines.append("")

    if include_failed_details and stats.failed_record_details:
        lines.append("Failed record details:")
        lines.append("-" * 50)
        for detail in stats.failed_record_details:
            lines.append(f"  Index:  {detail['index']}")
            lines.append(f"  Reason: {detail.get('message', detail.get('reason', 'Unknown'))}")
            lines.append("")
    return "\n".join(lines)
