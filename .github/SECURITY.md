# Security Policy

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: **Security -> Report a
vulnerability** on this repository. Do not open a public issue for a
security bug.

## Threat model summary

Find+ stores your location history locally, in `~/.findplus/`. It runs no
network service beyond a loopback-only HTTP API (`127.0.0.1:8647` by
default). Auth tokens and other secrets are stored at file mode `0600`
inside a `0700` directory, never in the database or in logs.

The app lock stops casual browsing. It does not encrypt the database;
anyone with access to this user account or the disk can read it. Use
FileVault.

See the wiki's [Privacy and threat
model](https://github.com/acamarata/findplus/wiki/Privacy-and-threat-model)
page for the full threat model.

## Supported versions

Only the latest released version receives security fixes.
