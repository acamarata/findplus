# Contributing

Find+ takes contributions through pull requests on
[GitHub](https://github.com/acamarata/findplus).

The full guide, including local setup, running tests, code style, and the
PR process, lives in
[`.github/CONTRIBUTING.md`](https://github.com/acamarata/findplus/blob/main/.github/CONTRIBUTING.md)
at the repository root. In short:

```bash
git clone https://github.com/acamarata/findplus.git
cd findplus
python3.12 -m venv .venv
./.venv/bin/pip install -e "./cli[dev]"
./.venv/bin/python -m pytest cli/tests -q
```

Open a PR against `main` from a `feature/your-feature` branch. All CI
checks in the gate checklist must be green before review.

Read [SECURITY.md](https://github.com/acamarata/findplus/blob/main/.github/SECURITY.md)
for how to report a vulnerability, and the
[Code of Conduct](https://github.com/acamarata/findplus/blob/main/.github/CODE_OF_CONDUCT.md)
for community standards.

---
[[Home]]
