#!/usr/bin/env python3
"""check-doc-links.py: dead relative-link finder for the wiki and README.

Purpose    : Fail when a relative markdown link, a wiki [[Page]] link, or a #anchor
             in .github/wiki/*.md or README.md points at nothing, and when Home.md
             does not link every wiki page.
Inputs     : none (run from anywhere; paths come from the repo root).
Outputs    : one line per problem on stdout; exit 1 if any, else 0.
Constraints: offline; external (http, mailto) links are ignored.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIKI = ROOT / ".github" / "wiki"
MD_LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")
WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$", re.M)


def slug(heading: str) -> str:
    text = re.sub(r"[`*_]", "", heading).strip().lower()
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", text))


def anchors(path: Path) -> set[str]:
    return {slug(h) for h in HEADING.findall(path.read_text(encoding="utf-8"))}


def check_file(path: Path) -> list[str]:
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
    problems = []
    for target in MD_LINK.findall(text):
        if re.match(r"[a-z][a-z0-9+.-]*:", target):
            continue
        file_part, _, frag = target.partition("#")
        dest = path if not file_part else (path.parent / file_part)
        if (
            file_part
            and not dest.exists()
            and (path.parent / (file_part + ".md")).exists()
        ):
            dest = path.parent / (file_part + ".md")
        if not dest.exists():
            problems.append(f"{path.relative_to(ROOT)}: missing file {target}")
        elif frag and dest.suffix == ".md" and slug(frag) not in anchors(dest):
            problems.append(f"{path.relative_to(ROOT)}: missing anchor {target}")
    if path.parent == WIKI:
        for name in WIKI_LINK.findall(text):
            if not (WIKI / f"{name.strip()}.md").exists():
                problems.append(
                    f"{path.relative_to(ROOT)}: missing wiki page [[{name}]]"
                )
    return problems


def home_coverage() -> list[str]:
    home = (WIKI / "Home.md").read_text(encoding="utf-8")
    linked = {m.split("#")[0] for m in MD_LINK.findall(home)}
    skip = {"Home", "_Sidebar", "_Footer"}
    return [
        f"Home.md does not link {p.stem}"
        for p in sorted(WIKI.glob("*.md"))
        if p.stem not in skip and p.stem not in linked
    ]


def main() -> int:
    problems = home_coverage()
    for path in [ROOT / "README.md", *sorted(WIKI.glob("*.md"))]:
        problems += check_file(path)
    print("\n".join(problems) if problems else "doc links ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
