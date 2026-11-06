"""CLI: dump everything the portal knows as JSON.

    VIACQUA_USERNAME=... VIACQUA_PASSWORD=... python -m custom_components.viacqua.api dump > dump.json
    python -m custom_components.viacqua.api readings
    python -m custom_components.viacqua.api invoices
    python -m custom_components.viacqua.api pdf <invoice_number> [out_dir]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .client import ViacquaClient


async def _run(args: argparse.Namespace) -> int:
    user = os.environ.get("VIACQUA_USERNAME")
    pwd = os.environ.get("VIACQUA_PASSWORD")
    if not user or not pwd:
        print("Set VIACQUA_USERNAME and VIACQUA_PASSWORD", file=sys.stderr)
        return 2
    async with ViacquaClient(user, pwd) as client:
        await client.login()
        if args.cmd == "readings":
            data = [r.as_dict() for r in await client.get_readings()]
        elif args.cmd == "invoices":
            data = [i.as_dict() for i in await client.get_invoices()]
        elif args.cmd == "selfreading":
            data = (await client.get_self_reading_info()).as_dict()
        elif args.cmd == "pdf":
            invoices = await client.get_invoices()
            inv = next((i for i in invoices if i.number == args.number), None)
            if inv is None:
                print(f"Invoice {args.number} not found", file=sys.stderr)
                return 1
            name, body = await client.download_invoice_pdf(inv)
            out = Path(args.out_dir) / name
            out.write_bytes(body)
            print(out)
            return 0
        else:  # dump
            data = {
                "user": client.display_name,
                "customer": (await client.get_customer()).as_dict(),
                "contracts": [c.as_dict() for c in await client.get_contracts()],
                "contract_detail": (await client.get_contract_detail()).as_dict(),
                "readings": [r.as_dict() for r in await client.get_readings()],
                "invoices": [i.as_dict() for i in await client.get_invoices()],
                "self_reading": (await client.get_self_reading_info()).as_dict(),
                "activities": [a.as_dict() for a in await client.get_activities()],
            }
        json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
        print()
        await client.logout()
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m custom_components.viacqua.api")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("dump")
    sub.add_parser("readings")
    sub.add_parser("invoices")
    sub.add_parser("selfreading")
    pdf = sub.add_parser("pdf")
    pdf.add_argument("number")
    pdf.add_argument("out_dir", nargs="?", default=".")
    args = p.parse_args()
    args.cmd = args.cmd or "dump"
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
