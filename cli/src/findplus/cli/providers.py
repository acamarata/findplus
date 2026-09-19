# Purpose: `findplus providers` — list installed LocationProviders and their status.
# Inputs: none (reads the process-wide provider registry).
# Outputs: a console table, or JSON with --json.
# Constraints: Click only (no Typer anywhere in this codebase); never raises on a
#              broken provider.
from __future__ import annotations

import json

import click

from findplus.providers.base import available_providers, get_provider


@click.command("providers")
@click.option("--json", "json_out", is_flag=True, help="Output as JSON")
def providers_cmd(json_out: bool) -> None:
    """List installed location providers and whether they are ready to poll."""
    rows = []
    for name in available_providers():
        try:
            p = get_provider(name)
            avail, reason = p.is_available()
            authed = p.is_authenticated() if avail else False
            rows.append(
                {
                    "name": p.name,
                    "display_name": p.display_name,
                    "available": avail,
                    "authenticated": authed,
                    "reason": reason,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "name": name,
                    "display_name": name,
                    "available": False,
                    "authenticated": False,
                    "reason": str(exc),
                }
            )
    if json_out:
        click.echo(json.dumps(rows, indent=2))
    else:
        click.echo(f"{'NAME':<22} {'AVAIL':<8} {'AUTHED':<10} REASON")
        for r in rows:
            avail, authed = r["available"], r["authenticated"]
            click.echo(f"{r['name']:<22} {avail!s:<8} {authed!s:<10} {r['reason']}")
