"""Helper functions for CLI operations."""

from datetime import UTC, datetime

import typer


def parse_timestamp(timestamp_str: str) -> datetime:
    """Parse a timestamp string in various formats.

    Args:
        timestamp_str (str): YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, or Unix timestamp.

    Returns:
        datetime: Timezone-aware (UTC) datetime object.

    Raises:
        typer.BadParameter: If the timestamp format is invalid.
    """
    try:
        return datetime.fromtimestamp(float(timestamp_str), tz=UTC)
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(timestamp_str, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue

    raise typer.BadParameter(f"Invalid timestamp format: '{timestamp_str}'.")
