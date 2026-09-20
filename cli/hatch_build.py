"""Hatchling build hook: force-include the dashboard and data files into the wheel.

Purpose    : Add every file under web/ to the wheel at findplus/web/static/ and
             every file under packaging/data/ at findplus/_data/, at build time
             rather than via a static force-include table, so the mapping works
             both from a repo checkout and from an unpacked sdist (where
             "../web" does not exist).
Inputs     : self.root (the directory holding this pyproject.toml at build
             time); for each source, either <root>/<dir> (sdist case) or
             <root>/../<dir> (repo case) must exist.
Outputs    : build_data["force_include"] entries mapping each source file to
             findplus/web/static/<relative path> or findplus/_data/<relative
             path>; the sdist's .gitignore entry removed.
Constraints: raises RuntimeError if neither location of a source exists, so a
             wheel can never ship silently without the dashboard or without the
             pinned icon table findplus.labels reads. Hatchling force-includes
             the repo's VCS exclusion files in every sdist and force_include
             beats `exclude`, so dropping .gitignore has to happen here rather
             than in pyproject.toml.
SPORT      : master-inventories.md § config-files (P1-E12-W5-S1-T1).
"""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

#: (directory relative to the repo root, sdist prefix, wheel prefix).
_SOURCES = [
    ("web", "web", "findplus/web/static"),
    ("packaging/data", "packaging/data", "findplus/_data"),
]


class DashboardHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        for rel_dir, sdist_prefix, wheel_prefix in _SOURCES:
            src_dir = Path(self.root) / rel_dir
            if not src_dir.is_dir():
                src_dir = Path(self.root).parent / rel_dir
            if not src_dir.is_dir():
                raise RuntimeError(f"{rel_dir} directory not found")
            for file in src_dir.rglob("*"):
                if not file.is_file():
                    continue
                rel_parts = file.relative_to(src_dir).parts
                if "__pycache__" in rel_parts or any(p.startswith(".") for p in rel_parts):
                    continue
                rel = file.relative_to(src_dir).as_posix()
                prefix = sdist_prefix if self.target_name == "sdist" else wheel_prefix
                build_data["force_include"][str(file)] = f"{prefix}/{rel}"
        for source, dest in list(build_data["force_include"].items()):
            if dest == ".gitignore":
                del build_data["force_include"][source]
