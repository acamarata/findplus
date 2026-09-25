"""`findplus selfcheck`: can this install sign in at all?

Purpose    : Three checks that only fail in a broken build, run by
             packaging/scripts/sidecar-smoke.sh against the frozen daemon:
             1. a multiprocessing child can start (Google sign-in's
                undetected_chromedriver launches Chrome that way; the v1.1.1
                dmg crashed there because the frozen entry point never called
                multiprocessing.freeze_support());
             2. the Apple Find My library is importable (v1.1.1 shipped
                without it, so Apple sign-in could never work in the app);
             3. every vendored GoogleFindMyTools module Find+ uses imports
                (the vendor tree ships as data, so PyInstaller never traced
                its imports and v1.1.1 lacked selenium.webdriver.support.ui).
Inputs     : --no-apple skips check 2 for a deliberate CLI-only install.
Outputs    : One line per check, exit 0 when every check passes, 1 otherwise.
Constraints: No network, no state dir writes, no browser launch.
"""

from __future__ import annotations

import importlib.util
import multiprocessing

import click

#: The vendored modules Find+ imports (sign-in, polling, decryption).
VENDOR_MODULES = (
    "chrome_driver",
    "Auth.auth_flow",
    "Auth.token_cache",
    "Auth.aas_token_retrieval",
    "Auth.username_provider",
    "Auth.fcm_receiver",
    "FMDNCrypto.foreign_tracker_cryptor",
    "KeyBackup.cloud_key_decryptor",
    "NovaApi.ExecuteAction.LocateTracker.decrypt_locations",
    "NovaApi.ExecuteAction.LocateTracker.location_request",
    "NovaApi.ListDevices.nbe_list_devices",
    "NovaApi.nova_request",
    "ProtoDecoders.decoder",
    "selenium.webdriver.support.ui",
    "undetected_chromedriver",
)


def _child(queue) -> None:
    """Runs in the spawned child: proves the interpreter re-entered cleanly."""
    queue.put("ok")


def spawn_works(timeout: float = 30.0) -> bool:
    """Start one child with the 'spawn' method (what macOS uses) and wait."""
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    proc = ctx.Process(target=_child, args=(queue,))
    proc.start()
    try:
        return queue.get(timeout=timeout) == "ok"
    except Exception:
        return False
    finally:
        proc.join(timeout=5)
        if proc.is_alive():
            proc.kill()


def vendor_import_failures() -> list[str]:
    """Import each vendored module Find+ needs; return 'module: error' lines."""
    from findplus.providers.findhub.bootstrap import ensure_gfmt_importable

    ensure_gfmt_importable()  # only puts the vendor tree on sys.path
    failures = []
    for name in VENDOR_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:  # report every failure, keep going
            failures.append(f"{name}: {exc}")
    return failures


@click.command()
@click.option("--no-apple", is_flag=True, help="Skip the Apple Find My library check.")
def selfcheck(no_apple: bool) -> None:
    """Check that this install can start sign-in helpers and has Apple support."""
    failures = vendor_import_failures()
    results = [
        ("helper process (Google sign-in)", spawn_works()),
        ("Google Find Hub modules", not failures),
    ]
    if not no_apple:
        results.append(("Apple Find My library", importlib.util.find_spec("findmy") is not None))
    for label, ok in results:
        click.echo(f"{'PASS' if ok else 'FAIL'}  {label}")
    for line in failures:
        click.echo(f"      {line}")
    if not all(ok for _, ok in results):
        raise SystemExit(1)
