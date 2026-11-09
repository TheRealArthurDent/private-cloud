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
| [OpenCloud](https://opencloud.eu/) – files, sync, sharing | role `opencloud`, at `https://opencloud.<host>` |
| [Paperless-ngx](https://docs.paperless-ngx.com/) – scanned documents, OCR, search | later |

## How it fits together

[raspberry](https://github.com/TheRealArthurDent/raspberry) sets up the host and the shared infrastructure: SSH,
Docker, the nginx reverse proxy and its certificate, the secrets (`.env` files from KeePass), and the resticprofile
backups. This repo only deploys the applications on top of it, the same way
[smart-home](https://github.com/TheRealArthurDent/smart-home) does on raspi. raspberry's `bootstrap.yaml` must have
run on the host first.

## OpenCloud

`opencloud/docker-compose.yaml` runs the official image (`opencloudeu/opencloud`, the stable releases) without a
host port: raspberry's nginx terminates TLS and proxies to `opencloud:9200` over the network `siz`. The first start
runs `opencloud init`, which creates the user `admin` with `OPENCLOUD_ADMIN_PASSWORD` and writes the generated
secrets to the volume `opencloud_config`. Users, files and the search index live in `opencloud_data`. Both volumes
are in the restic backup and come back by themselves on a fresh host (clean-slate restore).

What raspberry has to provide on the host before the first deployment:

| What | Where in raspberry |
| --- | --- |
| `/etc/docker/opencloud/.env` with `OPENCLOUD_ADMIN_PASSWORD` (keys in `opencloud/.env.example`) | `secrets` role, from KeePass |
| `/etc/ssl/certs/rootCA.pem`, and `opencloud` in the certificate's SANs | `certificate_check` role (`certificate_check_subdomains`) |
| A vhost `opencloud.<host>` that proxies to `http://opencloud:9200` (below) | `stack` role, nginx templates |
| `opencloud.<host>` resolving to the host | `configs/pihole.yaml` |
| The network `siz` and the helper `/usr/local/bin/restic-restore` | `stack` role |
| `opencloud` in `stack_backup_stacks`, once the first deployment wrote its marker | `restore_items.yaml` |

The nginx location (websockets for the web UI, no upload limit, long transfers). Its core, without the buffering
and timeout lines, was tested against the container, including the services verifying the private CA:

```nginx
location / {
    resolver 127.0.0.11;
    set $opencloud opencloud:9200;
    proxy_pass http://$opencloud;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    client_max_body_size 0;
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

On a new host without a backup, the first deployment needs `-e skip_opencloud_restore=true`.

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
scripts/github-settings.sh diff
scripts/github-settings.sh apply
```
