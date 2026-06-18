from __future__ import annotations


def month_index(value: str | None) -> int | None:
    if not value:
        return None

    parts = value.split("-")

    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return None

    return int(parts[0]) * 12 + int(parts[1])


def date_ranges_overlap(
    left_start: str | None,
    left_end: str | None,
    right_start: str | None,
    right_end: str | None,
) -> bool:
    left_start_index = month_index(left_start)
    left_end_index = month_index(left_end) or 999_999
    right_start_index = month_index(right_start)
    right_end_index = month_index(right_end) or 999_999

    if left_start_index is None or right_start_index is None:
        return False

    return left_start_index <= right_end_index and right_start_index <= left_end_index
