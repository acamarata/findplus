"""The `findplus version` command: installed version, optional update check.

Purpose    : Print the installed version and, with --check, compare it
             against the latest GitHub release.
Inputs     : --check flag.
Outputs    : The version string; "Up to date." or "Update available: ...".
Constraints: stdlib urllib only (zero new runtime dependency). A network
             failure during --check is never fatal — it prints to stderr
             and exits 0, matching every other read-only CLI command here.
"""

from __future__ import annotations

import importlib.metadata
import json
import urllib.error
import urllib.request

import click

_RELEASES_URL = "https://api.github.com/repos/acamarata/findplus/releases/latest"


@click.command("version")
@click.option("--check", is_flag=True, help="Check for a newer release on GitHub.")
def version_cmd(check: bool) -> None:
    """Print the installed version."""
    ver = importlib.metadata.version("findplus")
    click.echo(ver)
    if not check:
        return

    request = urllib.request.Request(
        _RELEASES_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"findplus/{ver}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read())
        latest = data["tag_name"].lstrip("v")
        if latest == ver:
            click.echo("Up to date.")
        else:
            click.echo(f"Update available: {data['tag_name']} (current: {ver})")
    except Exception as exc:
        click.echo(f"Could not check for updates: {exc}", err=True)
