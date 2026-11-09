"""opencloud/docker-compose.yaml and the opencloud role fit together and with raspberry's infrastructure."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "opencloud" / "docker-compose.yaml"
ROLE = ROOT / "ansible" / "roles" / "opencloud"


def compose():
    return yaml.safe_load(COMPOSE.read_text())


def service():
    return compose()["services"]["opencloud"]


def defaults():
    return yaml.safe_load((ROLE / "defaults" / "main.yaml").read_text())


def compose_up_task():
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yaml").read_text())
    return next(task for task in tasks if task.get("name") == "Ensure the stack is up")


def test_image_is_pinned():
    """Renovate updates the version; a floating tag would change the stack behind Ansible's back."""
    image = service()["image"]
    assert re.fullmatch(r"opencloudeu/opencloud:\d+\.\d+\.\d+", image), image


def test_no_port_is_published():
    """Only raspberry's nginx reaches OpenCloud, over the network siz; nothing listens on the host."""
    assert "ports" not in service()
    assert service()["networks"] == ["siz"]
    assert compose()["networks"]["siz"] == {"name": "siz", "external": True}


def test_nginx_terminates_tls_and_opencloud_verifies_its_certificate():
    environment = service()["environment"]
    assert environment["PROXY_TLS"] == "false"
    assert environment["PROXY_HTTP_ADDR"] == "0.0.0.0:9200"
    assert environment["OC_INSECURE"] == "false"


def test_the_root_ca_the_role_checks_is_mounted():
    root_ca = defaults()["opencloud_root_ca"]
    assert f"{root_ca}:/etc/ssl/certs/rootCA.pem:ro" in service()["volumes"]


def test_every_variable_comes_from_an_env_file():
    """Compose interpolates ${VAR} from settings.env (role) and .env (raspberry's secrets role)."""
    referenced = set(re.findall(r"\$\{(\w+)\}", COMPOSE.read_text()))
    settings = set(re.findall(r"^(\w+)=", (ROLE / "templates" / "settings.env.j2").read_text(), re.MULTILINE))
    secrets = set(re.findall(r"^(\w+)=", (ROOT / "opencloud" / ".env.example").read_text(), re.MULTILINE))
    assert settings.isdisjoint(secrets)
    assert referenced == settings | secrets


def test_env_example_holds_no_values():
    lines = (ROOT / "opencloud" / ".env.example").read_text().splitlines()
    entries = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    assert entries
    assert [line for line in entries if not re.fullmatch(r"[A-Z0-9_]+=", line)] == []


def test_healthcheck_uses_the_proxy_debug_endpoint():
    environment = service()["environment"]
    assert environment["PROXY_DEBUG_ADDR"] == "127.0.0.1:9205"
    assert "http://127.0.0.1:9205/readyz" in service()["healthcheck"]["test"]


def test_compose_up_fails_on_a_container_that_doesnt_come_up():
    module = compose_up_task()["community.docker.docker_compose_v2"]
    assert module["wait"] is True
    assert module["project_name"] == "{{ opencloud_project_name }}"


def test_compose_up_skips_files_check_mode_has_not_written():
    assert "not (ansible_check_mode and (opencloud_compose_file is changed or opencloud_settings is changed))" in (
        compose_up_task()["when"]
    )
