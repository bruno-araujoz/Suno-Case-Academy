"""Baixa uma URL e grava como fixture de teste com metadados (stdlib apenas)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

EXT_BY_TYPE = {
    "json": ".json",
    "pdf": ".pdf",
    "rss": ".xml",
    "xml": ".xml",
    "html": ".html",
    "csv": ".csv",
    "plain": ".txt",
}
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fonte")
    ap.add_argument("url")
    ap.add_argument("nome", nargs="?", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not re.fullmatch(r"[a-z0-9_]+", args.fonte):
        print("fonte deve ser snake_case (ex.: bcb_copom)", file=sys.stderr)
        return 1

    headers = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"}
    req = urllib.request.Request(args.url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - URL fornecida pelo usuário
        body = resp.read()
        status = resp.status
        ctype = resp.headers.get("Content-Type", "")

    ext = next((e for k, e in EXT_BY_TYPE.items() if k in ctype.lower()), ".bin")
    name = args.nome or datetime.now(UTC).strftime("%Y%m%d")
    out_dir = Path("tests/fixtures") / args.fonte
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}{ext}"
    if target.exists() and not args.force:
        print(f"{target} já existe; use --force para recapturar.", file=sys.stderr)
        return 1

    target.write_bytes(body)
    meta = {
        "url": args.url,
        "captured_at": datetime.now(UTC).isoformat(),
        "status": status,
        "content_type": ctype,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    (out_dir / f"{name}.meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(json.dumps({"saved": str(target), **meta}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
