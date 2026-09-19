# Contributing to Find+

## Getting started

```bash
git clone https://github.com/acamarata/findplus.git
cd findplus
python3.12 -m venv .venv
./.venv/bin/pip install -e "./cli[dev]"
./.venv/bin/playwright install chrome
```

## Running tests

```bash
./.venv/bin/python -m pytest cli/tests -q
```

Tests never touch the real Google or Apple account, the real `~/.findplus`,
or the network. A browser test needs Playwright's bundled Chromium, never
your system Chrome.

## Code style

Ruff enforces lint and formatting: `ruff check cli/src cli/tests` and
`ruff format --check cli/src cli/tests`. Files stay under 300 lines and
functions under 50 lines. No AI attribution in commit messages or code
comments.

## Submitting a PR

1. Fork the repository.
2. Create a branch named `feature/your-feature`.
3. Open a PR against `main`. Fill in the PR template's gate checklist.
4. All CI checks must be green before review.

## Reporting bugs

Use the bug report issue template. Include your `findplus --version`
output and, if relevant, log lines from `~/.findplus/logs/findplus.log`.

---
See also: [SECURITY.md](SECURITY.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
