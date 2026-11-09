# private-cloud – OpenCloud and Paperless on Raspberry Pi

Docker Compose stack for the private cloud: OpenCloud (files, sync, sharing) and later Paperless-ngx (documents,
OCR). It runs on `dungeon`, a Raspberry Pi 5 (8 GB, Debian/Raspberry Pi OS trixie, arm64) with an NVMe SSD for the
data and an external USB SSD for backups. The apps are reachable only from the home network and through WireGuard
(DNS through Pi-hole, certificates from the private root CA), never exposed to the internet.

## State of the repo

- **Scaffold only so far**: tooling, CI, rulesets, guard hook, inventory and `ansible/deploy.yaml` with the
  `--limit` guard. The `opencloud` role comes next, Paperless after it. Each app gets its own role and its own
  Compose project.
- **raspberry provides what this stack depends on**, as it does for smart-home on raspi: host setup, Docker, the
  nginx reverse proxy with its vhosts and certificate, the secrets files (rendered from KeePass by raspberry's
  `secrets` role), and the resticprofile backups. raspberry is being extended to manage dungeon as a second host
  (its `stack` role split into components per host, raspberry#239). Without raspberry's bootstrap on the host,
  this stack doesn't start.
- Each app restores its own state before it starts (clean-slate restore through raspberry's `restic-restore`
  helper, like smart-home#1).

## Layout

- `ansible/` – `deploy.yaml`, `inventory/hosts.yaml`, `requirements.yaml` (collections), `ansible.cfg`
- `tests/` – pytest tests (Claude hook, rulesets, repo hygiene, `--limit` guard)
- `.claude/` – Claude Code settings and the guard hook (`hooks/guard.py`)
- `.github/rulesets/` + `scripts/rulesets.sh` – rulesets for `main`, applied by the user (`rulesets.sh apply`)

## Hosts

| Host | Purpose |
| --- | --- |
| `dungeon` (192.168.1.5) | **Production** private cloud and backup target of raspi. Only the user deploys to it; hand them the commands. |
| `testbed` (192.168.1.7) | Test Pi, reachable only from the home network: propose the commands to the user (`--check --diff`, real run, second run with `changed=0`). |

`raspi` (192.168.1.2) is production too, but not part of this repo's inventory.

Always pass `--limit <host>` to `ansible-playbook`; `deploy.yaml` refuses to run without it.

A `PreToolUse` hook (`.claude/hooks/guard.py`, tests in `tests/test_guard_hook.py`) blocks the risky actions for
Claude: `ansible-playbook` against dungeon or raspi or without `--limit`, ssh/scp/rsync to dungeon or raspi, pushes
to `main`, force pushes, PR merges, `git add -f`, committing or printing `.env` files, and edits to the hook and
settings themselves. Don't work around a block; give the user the command or the proposed change instead.

## Secrets

Passwords live in KeePass and reach the Pi as `.env` files through raspberry's `secrets` role; this repo has no
KeePass access of its own. Never commit a `.env` file, never read or print one, and never put secret values into
config files in this repo; reference `${VAR}` from the env file instead. Each app documents its keys in an
`.env.example` without values. Tasks that handle secret values need `no_log: true`.

## Commands

Tooling lives in a venv at the repo root:

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pre-commit install
(cd ansible && ../.venv/bin/ansible-galaxy collection install -r requirements.yaml)
.venv/bin/pytest tests                                  # unit tests (the --limit guard tests need the collections)
(cd ansible && ../.venv/bin/ansible-lint --strict)     # must report 0 findings (CI blocks)
.venv/bin/pre-commit run --all-files                    # whitespace, YAML, gitleaks, renovate config, actionlint
```

When writing or changing an Ansible role, follow raspberry's `ansible-role` skill
(`.claude/skills/ansible-role/SKILL.md` there): FQCN, `no_log`, idempotence, a Molecule `verify.yaml` check per
change.

CI runs on every PR: unit tests (`tests.yaml`), Ansible lint (`ansible.yaml`), codespell, and reviewdog (misspell,
actionlint, yamllint, markdownlint). Required checks for `main` are in `.github/rulesets/`; a required job must
run on every PR (no `paths` filter), or `tests/test_rulesets.py` fails.

## Conventions

- Commit messages: conventional style (`feat:`, `fix:`, `test:`, `chore:`), referencing issues (`Refs #1`).
- Never commit or push to `main`. Branch off `main` and open a PR into `main`; the user merges.
- Container images are pinned and updated by Renovate; keep them pinned.
- Work test-driven, unless something speaks against it (then say why): write the test first and watch it fail
  for the right reason.
- YAML files use the `.yaml` extension, not `.yml`, unless a tool requires a fixed name (Molecule's `molecule.yml`).
- Name things after what they do, not after the host they run on: apps may move to another Pi.
- Everything in the repo is written in English (code, comments, docs, commit messages), even when the user
  chats in German.

## Working with the user

- Before changing code, give a short plan summary (what, which files, how tested).
- Answer in the language of the user's message (German or English); the repo itself stays English.
- Whenever a task would benefit from a skill you don't have, say so: which skill, what it would be for, and
  whether a ready-made one exists or it would have to be written.
