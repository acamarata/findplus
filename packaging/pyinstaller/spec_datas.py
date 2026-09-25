"""Which files each PyInstaller spec ships, and which it must not.

Purpose    : One definition of the datas walk, imported by BOTH
             findplus-daemon.spec (arm64) and findplus-daemon-x86_64.spec.
             The arm64 spec grew the filter for E1 packaging round 2 F4 and
             the Intel one did not, so an Intel release still embedded
             web/.claude/{AGENTS,CLAUDE}.md -- which the daemon then mounts at
             /static (E1 security round 3 F3). Two copies of a security filter
             is one copy too many.
Inputs     : The repo root, from the spec's SPECPATH.
Outputs    : A list of (source file, destination directory) pairs.
Constraints: Filtering changes what is PACKAGED, never the vendor tree itself
             (PRI rule 8), which is why the vendored project keeps its own
             dotfiles and loses only the __pycache__ a local run left behind.
"""

from __future__ import annotations

from pathlib import Path


def tree_datas(src_dir, dest_root: str, keep_dotted: bool = False):
    """Every file under `src_dir`, file by file, skipping caches and dotfiles.

    A bare (dir, dest) entry copies the tree verbatim, dotdirs included, and an
    owner-run release-local.sh builds from the WORKING tree, not a clean
    checkout. This is the same rel_parts test cli/hatch_build.py applies to the
    wheel.
    """
    out = []
    for file in sorted(Path(src_dir).rglob("*")):
        if not file.is_file():
            continue
        rel_parts = file.relative_to(src_dir).parts
        if "__pycache__" in rel_parts:
            continue
        if not keep_dotted and any(part.startswith(".") for part in rel_parts):
            continue
        out.append((str(file), "/".join((dest_root, *rel_parts[:-1]))))
    return out


def daemon_datas(root):
    """The three trees the sidecar ships, filtered."""
    root = Path(root)
    return [
        *tree_datas(root / "web", "findplus/web/static"),
        *tree_datas(root / "cli/src/findplus/db/migrations", "findplus/db/migrations"),
        *tree_datas(
            root / "cli/vendor/GoogleFindMyTools",
            "findplus/_vendor/GoogleFindMyTools",
            keep_dotted=True,
        ),
    ]


#: findmy's own dependency tree. anisette (local Apple anisette data) loads the
#: Unicorn CPU emulator's native library, so code, dylibs and dist-info all have
#: to ship. `fs` is a declared anisette dependency that nothing imports (anisette
#: has its own _fs module); collecting it needs pkg_resources, which current
#: setuptools no longer ships, so it is left out on purpose.
APPLE_PACKAGES = ("findmy", "anisette", "elftools", "srp", "unicorn", "bleak")
APPLE_DISTS = ("findmy", "anisette", "pyelftools", "srp", "unicorn", "bleak", "certifi")


def apple_extra():
    """findmy and its dependency tree, so the dmg can sign in to Apple.

    Returns (hiddenimports, datas, binaries). Find+ imports findmy lazily
    (importlib), so Analysis() never traced it and the v1.1.1 dmg shipped
    without it (needs=["apple_extra"]). The first 1.1.2 candidate bundled
    findmy but not libunicorn, and `import findmy` failed inside the app with
    "Failed to load the Unicorn dynamic library". A release built without the
    extra installed now fails here; FINDPLUS_ALLOW_NO_APPLE=1 opts out for a
    deliberate CLI-only build.
    """
    import importlib.util
    import os

    from PyInstaller.utils.hooks import (
        collect_data_files,
        collect_dynamic_libs,
        collect_submodules,
        copy_metadata,
    )

    if importlib.util.find_spec("findmy") is None:
        if os.environ.get("FINDPLUS_ALLOW_NO_APPLE") == "1":
            return [], [], []
        raise SystemExit(
            "findmy is not installed in the build environment: install the "
            "`apple` extra (pip install './cli[bundle,apple]') or set "
            "FINDPLUS_ALLOW_NO_APPLE=1 for a build without Apple Find My."
        )
    present = [pkg for pkg in APPLE_PACKAGES if importlib.util.find_spec(pkg) is not None]
    hidden = [name for pkg in present for name in collect_submodules(pkg)]
    # Static archives (unicorn ships a 24 MB libunicorn.a) are link-time only.
    datas = [d for pkg in present for d in collect_data_files(pkg) if not d[0].endswith(".a")]
    datas += [m for dist in APPLE_DISTS for m in copy_metadata(dist)]
    binaries = collect_dynamic_libs("unicorn")
    return hidden, datas, binaries


#: Third-party packages the vendored GoogleFindMyTools imports. The vendor tree
#: ships as DATA (source files, loaded at run time from findplus/_vendor), so
#: Analysis() never traces its imports: v1.1.1's dmg lacked
#: selenium.webdriver.support.ui and Google sign-in failed before Chrome opened.
#: Keep in step with cli/vendor/GoogleFindMyTools/requirements.txt (frida is
#: never a dependency, PRI rule 8).
VENDOR_PACKAGES = (
    "aiohttp",
    "bs4",
    "Cryptodome",
    "cryptography",
    "ecdsa",
    "google.protobuf",
    "gpsoauth",
    "h2",
    "http_ece",
    "httpx",
    "pyscrypt",
    "pytz",
    "requests",
    "selenium",
    "undetected_chromedriver",
)


def vendor_hiddenimports():
    """Every submodule of each package the vendored code imports."""
    import importlib.util

    from PyInstaller.utils.hooks import collect_submodules

    missing = [pkg for pkg in VENDOR_PACKAGES if importlib.util.find_spec(pkg) is None]
    if missing:
        raise SystemExit(f"vendored GoogleFindMyTools needs these packages: {', '.join(missing)}")
    return [name for pkg in VENDOR_PACKAGES for name in collect_submodules(pkg)]


#: Distribution names for VENDOR_PACKAGES. gpsoauth reads its own version via
#: importlib.metadata at import time, so the bundle needs the dist-info too, not
#: only the code (`findplus selfcheck` caught it: "No package metadata was
#: found for gpsoauth"). Copying all of them keeps the next one from biting.
VENDOR_DISTS = (
    "aiohttp",
    "beautifulsoup4",
    "pycryptodomex",
    "cryptography",
    "ecdsa",
    "protobuf",
    "gpsoauth",
    "h2",
    "http-ece",
    "httpx",
    "pyscrypt",
    "pytz",
    "requests",
    "selenium",
    "undetected-chromedriver",
)


def vendor_metadata():
    """dist-info of every vendored-code dependency (see VENDOR_DISTS)."""
    from PyInstaller.utils.hooks import copy_metadata

    return [entry for dist in VENDOR_DISTS for entry in copy_metadata(dist)]
