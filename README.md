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
| [Paperless-ngx](https://docs.paperless-ngx.com/) – scanned documents and mails, OCR, search | role `paperless`, at `https://paperless.<host>` |

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
| A restart of the containers labelled `root-ca.restart-on-change` when the root CA changes (the bind mount keeps the old file, and OpenCloud reads its trust store only at start) | `certificate_check` role |
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

### Upgrading to a new Production release

Renovate opens the PR; a new major (7.2 → 9.1) has manual steps that the role doesn't run. The commands below follow
the official [Upgrade 9.1.x guide][oc-upgrade-9.1] for this stack (container `opencloud`, volume `opencloud_config`,
Bleve search index). Of its breaking changes only the configuration patch and the search index concern this stack:
no Yjs, no custom thumbnails, quota, mail templates or web extensions, guest links off.

On the host, before deploying the new version:

```sh
# 1. A current backup, and the running version
docker exec resticprofile resticprofile backup
docker inspect --format '{{.Config.Image}}' opencloud

# 2. Stop OpenCloud and patch opencloud.yaml with the new image (`opencloud init --diff` writes opencloud.config.patch)
docker stop opencloud
# OC_INSECURE=false should answer init's question about disabling certificate checks (as in the compose file); answer `no` if it still asks
docker run --rm -it --user 1000:1000 -e OC_INSECURE=false --entrypoint /bin/sh -v opencloud_config:/etc/opencloud opencloudeu/opencloud:9.1.1
#   inside the container:
#   cd /etc/opencloud && opencloud init --diff
#   cat opencloud.config.patch                          # review; it may drop the thumbnails section, that's expected
#   patch --dry-run opencloud.yaml < opencloud.config.patch && patch opencloud.yaml < opencloud.config.patch
#   exit
```

Then deploy as usual (`ansible-playbook deploy.yaml --limit <host>`, `--check --diff` first), and on the host:

```sh
# 3. Rebuild the versioned search index (since 8.x); old files aren't found until it's done. Takes a while on the Pi.
docker exec opencloud opencloud search index --all-spaces --force-rescan
# 4. Once older files show up in the web UI's search, remove the old, unversioned index
docker exec opencloud rm -r /var/lib/opencloud/search/bleve
docker logs --tail=200 opencloud
```

Check afterwards: sign in, upload and download, spaces and shares, search, previews.

[oc-upgrade-9.1]: https://docs.opencloud.eu/docs/next/admin/maintenance/upgrade/production/upgrade-9.1.x

## Paperless-ngx

`paperless/docker-compose.yaml` runs five containers as the Compose project `paperless`:

| Service | Image | Purpose |
| --- | --- | --- |
| `webserver` | `ghcr.io/paperless-ngx/paperless-ngx` | Web UI, consumer, OCR, mail fetching |
| `db` | `postgres` (alpine) | Database |
| `broker` | `valkey/valkey` (alpine) | Task queue, nothing on disk |
| `gotenberg` | `gotenberg/gotenberg` | HTML mails (Chromium) and office files (LibreOffice) to PDF |
| `tika` | `apache/tika` | Text and metadata of office files and mails |

Every container runs as a non-root user without capabilities, with memory and PID limits; all but the webserver
have a read-only root file system. Database, broker and parsers sit on the internal network `backend` without
internet access. Only the webserver joins `siz` (nginx proxies to `paperless-webserver:8000`) and `outbound`, and
resolves names through infrastructure's outbound Pi-hole, which allows only the IMAP server of the mail account.
Gotenberg runs without JavaScript and refuses to fetch any URL (private or public).

Settings worth knowing before the first document: OCR in `deu+eng`, file names
`{{ created_year }}/{{ correspondent }}/{{ title }}` (changing this later renames every file), one task worker
with two threads. The user `admin` is created on the first start with `PAPERLESS_ADMIN_PASSWORD`; personal accounts,
the mail account and the mail rules are set up in the web UI and live in the database, not in this repo. Mail rules
read one dedicated folder or account, not a whole inbox.

Paperless supports only the Gotenberg and Tika majors its own compose files use (`docker/compose/` upstream), so
`renovate.json` caps both at the pinned major. Every Paperless update PR carries a prompt in its description: hand it
to Claude to align Gotenberg and Tika with the new Paperless version on that branch, and to raise a cap when upstream
moves to a new major.

### Backup and restore

The live database volume `paperless_pgdata` is not backed up. A systemd timer (`paperless-db-dump.timer`, 02:45)
writes `pg_dump` into the volume `paperless_dbdump` before resticprofile's run at 03:00; a failed dump keeps the
previous file. On a fresh host the clean-slate restore brings back `data`, `media`, `consume`, `export` and
`dbdump`, and Postgres imports `paperless.sql.gz` on its first start, before it accepts connections and before
the webserver starts. The same happens whenever `paperless_pgdata` is removed.

A Postgres major upgrade uses the same path: Postgres 18+ keeps its data in a directory per major version, so a new
major starts empty and imports the dump. Run `sudo systemctl start paperless-db-dump.service` right before the
deployment, so the dump is current; Renovate opens these PRs only after approval in the dependency dashboard.

What infrastructure has to provide on the host before the first deployment:

| What | Where in infrastructure |
| --- | --- |
| The Compose secret files `secret_key`, `admin_password`, `db_password` (owner uid 1000) and `postgres_password` (uid 70) in `/etc/docker/paperless/secrets/`, mode 0400 | `secrets` role (`secrets_paperless`), from KeePass |
| `paperless` in the certificate's SANs | `certificate_check` role (`certificate_check_subdomains`) |
| A vhost `paperless.<host>` that proxies to `http://paperless-webserver:8000` (below) | `reverse_proxy` role |
| `paperless.<host>` resolving to the host | `configs/pihole.yaml` |
| The networks `siz` and `outbound`, and the helper `/usr/local/bin/restic-restore` | `stack` role |
| The IMAP server of the mail account allowed in the outbound Pi-hole | `configs/pihole.yaml` |
| `/source/docker-volumes/paperless_pgdata` excluded from the backup | `resticprofile` role, `excludes.j2` |
| `paperless` in `stack_backup_stacks`, once the first deployment wrote its marker | `restore_items.yaml` |

The nginx location (websockets for the status updates, large uploads):

```nginx
location / {
    resolver 127.0.0.11;
    set $paperless paperless-webserver:8000;
    proxy_pass http://$paperless;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    client_max_body_size 100M;
    proxy_read_timeout 300s;
}
```

On a new host without a backup, the first deployment needs `-e skip_paperless_restore=true`.

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
