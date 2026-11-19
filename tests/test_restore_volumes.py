"""Each app role lists the volumes infrastructure's restic-restore brings back on a fresh host.

Every named volume of an app's compose file holds state that doesn't come from IaC. Each is either listed in
<app>_restore_volumes, with the services that mount it, or in <app>_unrestored_volumes with the reason (Paperless'
live database is excluded from the backup; a dump of it is restored instead).
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
APPS = ["opencloud", "paperless"]


def compose(app):
    return yaml.safe_load((ROOT / app / "docker-compose.yaml").read_text())


def defaults(app):
    return yaml.safe_load((ROOT / "ansible" / "roles" / app / "defaults" / "main.yaml").read_text())


def restore_volumes(app):
    return defaults(app)[f"{app}_restore_volumes"]


def unrestored_volumes(app):
    return defaults(app).get(f"{app}_unrestored_volumes", {})


def mounting_services(app, volume):
    return sorted(
        name
        for name, service in compose(app)["services"].items()
        if any(str(mount).split(":")[0] == volume for mount in service.get("volumes", []))
    )


@pytest.mark.parametrize("app", APPS)
def test_every_named_volume_is_restored_or_says_why_not(app):
    restored, unrestored = set(restore_volumes(app)), set(unrestored_volumes(app))
    assert restored.isdisjoint(unrestored)
    assert restored | unrestored == set(compose(app)["volumes"])
    assert all(unrestored_volumes(app).values())


@pytest.mark.parametrize("app", APPS)
def test_each_volume_names_the_services_that_mount_it(app):
    for volume, item in restore_volumes(app).items():
        assert sorted(item["services"]) == mounting_services(app, volume), volume


@pytest.mark.parametrize("app", APPS)
def test_each_volume_says_what_it_keeps_from_a_restore(app):
    for volume, item in restore_volumes(app).items():
        assert isinstance(item["preserve"], list), volume
        assert all(not pattern.startswith("/") for pattern in item["preserve"]), volume
        assert item["note"], volume


@pytest.mark.parametrize("app", APPS)
def test_every_service_has_a_container_name(app):
    """The restore helper stops containers by name."""
    for name, service in compose(app)["services"].items():
        assert service.get("container_name"), name


def test_paperless_restores_the_dump_and_not_the_live_database():
    assert "dbdump" in restore_volumes("paperless")
    assert set(unrestored_volumes("paperless")) == {"pgdata"}
