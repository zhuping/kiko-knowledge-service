from __future__ import annotations

from sqlalchemy import inspect


def model_dict(item, *, exclude: set[str] | None = None) -> dict:
    excluded = exclude or set()
    return {
        column.key: getattr(item, column.key)
        for column in inspect(item).mapper.column_attrs
        if column.key not in excluded
    }
