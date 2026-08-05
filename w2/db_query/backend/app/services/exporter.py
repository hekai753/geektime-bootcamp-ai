"""Result formatting utilities for data export (CSV / JSON)."""

import csv
import io
import json

from app.models.schemas import QueryResult


def to_csv(result: QueryResult) -> str:
    """Render a QueryResult as RFC 4180 compliant CSV.

    Column order follows ``result.columns``. Rows are written via
    ``csv.DictWriter`` so missing keys become empty fields and extra keys are
    ignored. Non-string scalars (datetime, Decimal, ...) are stringified by
    the csv writer. Line terminator is ``\\r\\n`` per RFC 4180.
    """
    fieldnames = [col.name for col in result.columns]
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=fieldnames,
        extrasaction="ignore",
        lineterminator="\r\n",
    )
    writer.writeheader()
    writer.writerows(result.rows)
    return buffer.getvalue()


def to_json(result: QueryResult) -> str:
    """Render a QueryResult as pretty-printed JSON (array of row objects).

    ``default=str`` stringifies any non-JSON-native values such as datetime
    or Decimal, mirroring how the MySQL adapter already iso-formats datetimes.
    """
    return json.dumps(
        result.rows,
        indent=2,
        ensure_ascii=False,
        default=str,
    )
