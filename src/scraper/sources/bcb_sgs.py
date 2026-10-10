"""BCB SGS time series (Selic, IPCA, FX, CDI) — stored in market_series for fact-checking.

Not a document source: returns rows. Incremental by the last stored date per series.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from ..core.http import HttpClient
from ..core.logging import get_logger
from ..core.models import SAO_PAULO

log = get_logger("source.bcb_sgs")

URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
SERIES: dict[int, str] = {
    432: "Selic meta (% a.a.)",
    433: "IPCA mensal (%)",
    13522: "IPCA acumulado 12 meses (%)",
    1: "Dólar comercial venda (R$)",
    12: "CDI diário (%)",
}

Row = tuple[int, str, date, Decimal]


async def fetch_series(
    http: HttpClient, since: datetime, last_dates: dict[int, date] | None = None
) -> tuple[list[Row], dict[str, object]]:
    """Fetch all configured series from max(since, last stored date + 1 day)."""
    rows: list[Row] = []
    report: dict[str, object] = {
        "source": "bcb_sgs",
        "status": "ok",
        "items_seen": 0,
        "items_valid": 0,
    }
    today = datetime.now(SAO_PAULO).date()  # SGS dates are Brazilian calendar days
    for code, name in SERIES.items():
        start = since.date()
        if last_dates and code in last_dates:
            start = max(start, last_dates[code] + timedelta(days=1))
        if start > today:
            continue
        result = await http.get(
            URL.format(code=code),
            params={
                "formato": "json",
                "dataInicial": start.strftime("%d/%m/%Y"),
                "dataFinal": today.strftime("%d/%m/%Y"),
            },
        )
        if result.status == 404:  # SGS answers 404 when the window has no new values
            continue
        payload = result.json() if result.ok else None
        if not isinstance(payload, list):
            report["status"] = "degraded"
            report["error"] = f"série {code}: {result.error or 'payload inválido'}"
            continue
        for item in payload:
            report["items_seen"] = int(report["items_seen"]) + 1
            try:
                day, month, year = map(int, str(item["data"]).split("/"))
                rows.append((code, name, date(year, month, day), Decimal(str(item["valor"]))))
                report["items_valid"] = int(report["items_valid"]) + 1
            except (KeyError, ValueError, InvalidOperation):
                continue
    return rows, report
