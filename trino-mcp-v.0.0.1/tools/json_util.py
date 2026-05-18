"""JSON helpers for Trino result types."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal


class TrinoJsonEncoder(json.JSONEncoder):
    def default(self, o: object) -> object:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return super().default(o)


def dumps(data: object) -> str:
    return json.dumps(data, cls=TrinoJsonEncoder)
