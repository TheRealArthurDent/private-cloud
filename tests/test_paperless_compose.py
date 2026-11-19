"""paperless/docker-compose.yaml and the paperless role fit together, with infrastructure and with the hardening plan.

The hardening follows the security issue linked from private-cloud#15: the parsers (Gotenberg, Tika) and the
backends (Postgres, Valkey) sit on an internal network without internet access, only the webserver reaches nginx
and, through the outbound Pi-hole, the IMAP server.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "paperless" / "docker-compose.yaml"
ROLE = ROOT / "ansible" / "roles" / "paperless"

# The address of infrastructure's outbound Pi-hole on the network outbound, the egress filter by DNS
OUTBOUND_DNS = "172.30.1.153"

IMAGES = {
    "webserver": r"ghcr\.io/paperless-ngx/paperless-ngx:\d+\.\d+\.\d+",
    "db": r"postgres:\d+\.\d+-alpine",
    "broker": r"valkey/valkey:\d+\.\d+\.\d+-alpine",
    "gotenberg": r"gotenberg/gotenberg:\d+\.\d+\.\d+",
    "tika": r"apache/tika:\d+\.\d+\.\d+\.\d+",
}


def compose():
    return yaml.safe_load(COMPOSE.read_text())


def services():
    return compose()["services"]


def service(name):
    return services()[name]


def defaults():
    return yaml.safe_load((ROLE / "defaults" / "main.yaml").read_text())


def tasks():
    return yaml.safe_load((ROLE / "tasks" / "main.yaml").read_text())


def task(name):
    return next(t for t in tasks() if t.get("name") == name)


def test_the_stack_has_the_five_services():
    assert set(services()) == set(IMAGES)


@pytest.mark.parametrize("name", sorted(IMAGES))
def test_images_are_pinned(name):
    """Renovate updates the versions; a floating tag would change the stack behind Ansible's back."""
    image = service(name)["image"]
    assert re.fullmatch(IMAGES[name], image), image


def test_gotenberg_has_chromium_and_libreoffice():
    """HTML mails need Chromium, office files LibreOffice: neither the -chromium nor the -libreoffice variant."""
    assert not re.search(r"-(chromium|libreoffice)", service("gotenberg")["image"])


@pytest.mark.parametrize("name", sorted(IMAGES))
def test_no_port_is_published(name):
    assert "ports" not in service(name)


def test_only_the_webserver_leaves_the_internal_network():
    networks = compose()["networks"]
    assert networks["backend"].get("internal") is True
    assert networks["siz"] == {"name": "siz", "external": True}
    assert networks["outbound"] == {"name": "outbound", "external": True}
    assert sorted(service("webserver")["networks"]) == ["backend", "outbound", "siz"]
    for name in ("db", "broker", "gotenberg", "tika"):
        assert service(name)["networks"] == ["backend"], name


def test_the_webserver_resolves_names_through_the_egress_filter():
    """The outbound Pi-hole denies every domain except the allowed ones (the IMAP server)."""
    assert service("webserver")["dns"] == [OUTBOUND_DNS]


@pytest.mark.parametrize("name", sorted(IMAGES))
def test_every_container_is_hardened(name):
    svc = service(name)
    assert svc["cap_drop"] == ["ALL"], name
    assert "cap_add" not in svc, name
    assert "no-new-privileges:true" in svc["security_opt"], name
    assert "privileged" not in svc, name


@pytest.mark.parametrize("name", sorted(IMAGES))
def test_every_container_runs_as_a_non_root_user(name):
    user = str(service(name).get("user", ""))
    assert re.fullmatch(r"[1-9]\d*:[1-9]\d*", user), f"{name}: user {user!r}"


@pytest.mark.parametrize("name", ["db", "broker", "gotenberg", "tika"])
def test_backends_and_parsers_have_a_read_only_root_filesystem(name):
    svc = service(name)
    assert svc["read_only"] is True, name
    assert any(str(path).startswith("/tmp") for path in svc.get("tmpfs", [])), name


@pytest.mark.parametrize("name", sorted(IMAGES))
def test_memory_and_pids_are_limited(name):
    """A parser bomb must not take down OpenCloud on the same Pi."""
    svc = service(name)
    assert re.fullmatch(r"\d+[mg]", str(svc["mem_limit"])), name
    assert int(svc["pids_limit"]) > 0, name


@pytest.mark.parametrize("name", sorted(IMAGES))
def test_containers_have_names_restart_and_local_logging(name):
    svc = service(name)
    assert svc["container_name"].startswith("paperless-"), name
    assert svc["restart"] == "unless-stopped", name
    assert svc["logging"] == {"driver": "local"}, name


def gotenberg_flags():
    command = service("gotenberg")["command"]
    assert command[0] == "gotenberg"
    return dict(arg.removeprefix("--").split("=", 1) for arg in command[1:])


def test_gotenberg_renders_without_javascript_and_fetches_nothing():
    flags = gotenberg_flags()
    assert flags["chromium-disable-javascript"] == "true"
    assert flags["chromium-deny-private-ips"] == "true"
    assert flags["chromium-deny-public-ips"] == "true"
    assert flags["api-disable-download-from"] == "true"
    assert flags["webhook-disable"] == "true"


def test_gotenberg_keeps_the_default_deny_list_and_no_allow_list():
    """A match in the allow list bypasses the IP checks; the default deny list rejects file: outside /tmp."""
    flags = gotenberg_flags()
    assert "chromium-allow-list" not in flags
    assert "chromium-deny-list" not in flags
    assert "chromium-disable-web-security" not in flags
    assert "chromium-allow-file-access-from-files" not in flags


def test_the_webserver_uses_the_other_services():
    environment = service("webserver")["environment"]
    assert environment["PAPERLESS_DBENGINE"] == "postgresql"
    assert environment["PAPERLESS_DBHOST"] == "db"
    assert environment["PAPERLESS_REDIS"] == "redis://broker:6379"
    assert environment["PAPERLESS_TIKA_ENABLED"] == "true"
    assert environment["PAPERLESS_TIKA_ENDPOINT"] == "http://tika:9998"
    assert environment["PAPERLESS_TIKA_GOTENBERG_ENDPOINT"] == "http://gotenberg:3000"


def test_the_webserver_waits_for_a_ready_database():
    depends_on = service("webserver")["depends_on"]
    assert depends_on["db"]["condition"] == "service_healthy"
    assert depends_on["broker"]["condition"] == "service_healthy"


def test_the_database_is_healthy_only_after_its_init_scripts():
    """During initdb and the import of a dump, Postgres listens only on its socket, so a TCP check waits for both."""
    test = " ".join(service("db")["healthcheck"]["test"])
    assert "pg_isready" in test
    assert "-h 127.0.0.1" in test


def test_the_database_dump_is_imported_by_an_empty_database():
    """The nightly dump lands in the volume dbdump; Postgres runs *.sql.gz in initdb.d when its data dir is new."""
    assert "dbdump:/docker-entrypoint-initdb.d:ro" in service("db")["volumes"]
    assert defaults()["paperless_db_dump_file"] == "paperless.sql.gz"


def test_the_live_database_is_a_volume_of_its_own():
    assert "pgdata:/var/lib/postgresql" in service("db")["volumes"]


def test_the_broker_keeps_nothing_on_disk():
    """Valkey is only the task queue; a lost queue is rebuilt by the schedules, so no volume and no snapshots."""
    svc = service("broker")
    assert "volumes" not in svc
    command = svc["command"]
    assert command[command.index("--save") + 1] == ""
    assert command[command.index("--appendonly") + 1] == "no"


def test_ocr_languages_and_file_names_are_set_before_the_first_document():
    environment = service("webserver")["environment"]
    assert environment["PAPERLESS_OCR_LANGUAGE"] == "deu+eng"
    assert environment["PAPERLESS_FILENAME_FORMAT"] == "{{ created_year }}/{{ correspondent }}/{{ title }}"
    assert environment["PAPERLESS_TIME_ZONE"] == "Europe/Berlin"


def test_the_pi_runs_one_task_worker():
    environment = service("webserver")["environment"]
    assert environment["PAPERLESS_TASK_WORKERS"] == "1"
    assert environment["PAPERLESS_THREADS_PER_WORKER"] == "2"
    assert environment["PAPERLESS_WEBSERVER_WORKERS"] == "1"


def test_the_ocr_languages_are_the_installed_ones():
    """Rootless Paperless can't install languages at start (PAPERLESS_OCR_LANGUAGES)."""
    assert "PAPERLESS_OCR_LANGUAGES" not in service("webserver")["environment"]


def test_every_variable_comes_from_the_settings_file():
    """Compose interpolates ${VAR} only from settings.env (role); no secret passes through an env file."""
    referenced = set(re.findall(r"\$\{(\w+)\}", COMPOSE.read_text()))
    settings = set(re.findall(r"^(\w+)=", (ROLE / "templates" / "settings.env.j2").read_text(), re.MULTILINE))
    assert referenced == settings
    assert not (ROOT / "paperless" / ".env.example").exists()


# Compose secrets (homelab-security#1): secret -> (service, variable reading /run/secrets/<secret>, container uid)
SECRETS = {
    "secret_key": ("webserver", "PAPERLESS_SECRET_KEY_FILE", 1000),
    "admin_password": ("webserver", "PAPERLESS_ADMIN_PASSWORD_FILE", 1000),
    "db_password": ("webserver", "PAPERLESS_DBPASS_FILE", 1000),
    "postgres_password": ("db", "POSTGRES_PASSWORD_FILE", 70),
}


def test_secrets_are_compose_secret_files_of_infrastructure():
    """infrastructure's secrets role writes them from KeePass, owned by the container user that reads them."""
    assert compose()["secrets"] == {
        name: {"file": f"/etc/docker/paperless/secrets/{name}"} for name in SECRETS
    }
    assert sorted(defaults()["paperless_secrets"]) == sorted(SECRETS)


@pytest.mark.parametrize("name", sorted(SECRETS))
def test_each_secret_reaches_its_service_as_a_file(name):
    svc_name, variable, uid = SECRETS[name]
    svc = service(svc_name)
    assert name in svc["secrets"]
    assert svc["environment"][variable] == f"/run/secrets/{name}"
    # Compose bind-mounts the file as it is: only its owner (the container user) can read it
    assert str(svc["user"]).split(":")[0] == str(uid)
    assert defaults()["paperless_secrets"][name] == uid


def test_no_secret_value_is_in_the_environment():
    for name, svc in services().items():
        environment = svc.get("environment", {})
        for key in ("PAPERLESS_SECRET_KEY", "PAPERLESS_ADMIN_PASSWORD", "PAPERLESS_DBPASS", "POSTGRES_PASSWORD"):
            assert key not in environment, f"{name}: {key}"
    assert set(service("broker").get("secrets", [])) == set()
    assert "secrets" not in service("gotenberg") and "secrets" not in service("tika")


def test_compose_up_fails_on_a_container_that_doesnt_come_up():
    module = task("Ensure the stack is up")["community.docker.docker_compose_v2"]
    assert module["wait"] is True
    assert module["project_name"] == "{{ paperless_project_name }}"


def test_compose_up_skips_files_check_mode_has_not_written():
    assert "not (ansible_check_mode and (paperless_compose_file is changed or paperless_settings is changed))" in (
        task("Ensure the stack is up")["when"]
    )


def test_the_database_dump_runs_before_the_backup():
    """infrastructure's resticprofile backs up at 03:00; the dump must be done by then."""
    hour, minute = map(int, defaults()["paperless_db_dump_time"].split(":"))
    assert (hour, minute) < (3, 0)
    assert hour >= 1
