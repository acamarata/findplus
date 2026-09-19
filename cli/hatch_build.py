"""Hatchling build hook: force-include the dashboard into the wheel.

Purpose    : Add every file under web/ to the wheel at findplus/web/static/,
             at build time rather than via a static force-include table, so
             the mapping works both from a repo checkout and from an
             unpacked sdist (where "../web" does not exist).
Inputs     : self.root (the directory holding this pyproject.toml at build
             time); either <root>/web (sdist case) or <root>/../web (repo
             case) must exist.
Outputs    : build_data["force_include"] entries mapping each source file to
             findplus/web/static/<relative path>.
Constraints: raises RuntimeError if neither web/ location exists, so a wheel
             can never ship silently without the dashboard.
SPORT      : master-inventories.md § config-files (P1-E12-W5-S1-T1).
"""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class DashboardHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        web_dir = Path(self.root) / "web"
        if not web_dir.is_dir():
            web_dir = Path(self.root).parent / "web"
        if not web_dir.is_dir():
            raise RuntimeError("dashboard directory not found")
        for file in web_dir.rglob("*"):
            if not file.is_file():
                continue
            rel_parts = file.relative_to(web_dir).parts
            if "__pycache__" in rel_parts or any(p.startswith(".") for p in rel_parts):
                continue
            rel = file.relative_to(web_dir).as_posix()
            build_data["force_include"][str(file)] = f"findplus/web/static/{rel}"
