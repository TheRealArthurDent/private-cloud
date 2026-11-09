# private-cloud

Private cloud stack on Raspberry Pi: OpenCloud for files and Paperless-ngx for documents, deployed with Ansible and
Docker Compose.

[![Tests](https://github.com/TheRealArthurDent/private-cloud/actions/workflows/tests.yaml/badge.svg)](https://github.com/TheRealArthurDent/private-cloud/actions/workflows/tests.yaml)
[![Ansible Tests](https://github.com/TheRealArthurDent/private-cloud/actions/workflows/ansible.yaml/badge.svg)](https://github.com/TheRealArthurDent/private-cloud/actions/workflows/ansible.yaml)
[![Spell Check](https://github.com/TheRealArthurDent/private-cloud/actions/workflows/spell-check.yaml/badge.svg)](https://github.com/TheRealArthurDent/private-cloud/actions/workflows/spell-check.yaml)

The stack runs on `dungeon`, a Raspberry Pi 5 (8 GB) with an NVMe SSD for the data and an external USB SSD for
backups. It is reachable only from the home network and through the WireGuard VPN, under names that Pi-hole
resolves and with certificates from the private root CA.

| App | Status |
| --- | --- |
| [OpenCloud](https://opencloud.eu/) – files, sync, sharing | planned |
| [Paperless-ngx](https://docs.paperless-ngx.com/) – scanned documents, OCR, search | later |

## How it fits together

[raspberry](https://github.com/TheRealArthurDent/raspberry) sets up the host and the shared infrastructure: SSH,
Docker, the nginx reverse proxy and its certificate, the secrets (`.env` files from KeePass), and the resticprofile
backups. This repo only deploys the applications on top of it, the same way
[smart-home](https://github.com/TheRealArthurDent/smart-home) does on raspi. raspberry's `bootstrap.yaml` must have
run on the host first.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pre-commit install
(cd ansible && ../.venv/bin/ansible-galaxy collection install -r requirements.yaml)
.venv/bin/pytest tests
(cd ansible && ../.venv/bin/ansible-lint --strict)
```

## Deployment

From `ansible/`, always with `--limit` to one host and a dry run first:

```sh
../.venv/bin/ansible-playbook deploy.yaml --limit testbed --check --diff
../.venv/bin/ansible-playbook deploy.yaml --limit testbed
```

A second run must report `changed=0`. Notes for Claude Code are in `CLAUDE.md`.

## Rulesets and repository settings

The rulesets for `main` live in `.github/rulesets/`, the other repository settings (auto merge, deleting merged
branches, secret scanning with push protection) in `.github/repo-settings.json`. Apply them once after cloning, and
after every change to those files (needs `gh` logged in as admin, and `jq`):

```sh
scripts/rulesets.sh diff
scripts/rulesets.sh apply
scripts/repo-settings.sh diff
scripts/repo-settings.sh apply
```
