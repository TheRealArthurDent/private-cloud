"""The opencloud role lists the volumes raspberry's restic-restore brings back on a fresh host.

Every named volume of opencloud/docker-compose.yaml holds state that doesn't come from IaC, so each is listed in
opencloud_restore_volumes, with the services that mount it.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "opencloud" / "docker-compose.yaml"
DEFAULTS = ROOT / "ansible" / "roles" / "opencloud" / "defaults" / "main.yaml"


def compose():
    return yaml.safe_load(COMPOSE.read_text())


def restore_volumes():
    return yaml.safe_load(DEFAULTS.read_text())["opencloud_restore_volumes"]


def mounting_services(volume):
    return sorted(
        name
        for name, service in compose()["services"].items()
        if any(str(mount).split(":")[0] == volume for mount in service.get("volumes", []))
    )


def test_every_named_volume_is_restored():
    assert set(restore_volumes()) == set(compose()["volumes"])


def test_each_volume_names_the_services_that_mount_it():
    for volume, item in restore_volumes().items():
        assert sorted(item["services"]) == mounting_services(volume), volume


def test_each_volume_says_what_it_keeps_from_a_restore():
    for volume, item in restore_volumes().items():
        assert isinstance(item["preserve"], list), volume
        assert all(not pattern.startswith("/") for pattern in item["preserve"]), volume
        assert item["note"], volume


def test_every_service_has_a_container_name():
    """The restore helper stops containers by name."""
    for name, service in compose()["services"].items():
        assert service.get("container_name"), name
