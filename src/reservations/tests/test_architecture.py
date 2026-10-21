"""L2 — the repeatable check that protects the architecture rules accepted in ADR-01."""

import importlib.util
from pathlib import Path

import pytest

CHECKER = Path(__file__).resolve().parents[3] / "scripts" / "check_architecture.py"


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("check_architecture", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_application_obeys_the_architecture_rules(checker):
    assert checker.violations() == []


def test_the_check_detects_a_status_write_outside_the_lifecycle_owner(checker, tmp_path):
    app = tmp_path / "src" / "reservations"
    app.mkdir(parents=True)
    (app / "views.py").write_text(
        "def confirm(reservation):\n    reservation.status = 'CONFIRMED'\n    reservation.save()\n"
    )

    report = checker.violations(app)

    assert len(report) == 1
    assert "views.py:2" in report[0]
    assert "writes Reservation.status" in report[0]


def test_the_check_detects_a_bulk_status_update_outside_the_lifecycle_owner(checker, tmp_path):
    app = tmp_path / "src" / "reservations"
    app.mkdir(parents=True)
    (app / "sweeper.py").write_text(
        "def expire(queryset):\n    return queryset.update(status='EXPIRED')\n"
    )

    report = checker.violations(app)

    assert len(report) == 1
    assert "sweeper.py:2" in report[0]


def test_the_check_detects_a_domain_module_importing_the_web_framework(checker, tmp_path):
    app = tmp_path / "src" / "reservations"
    app.mkdir(parents=True)
    (app / "availability.py").write_text("from rest_framework import serializers\n")

    report = checker.violations(app)

    assert len(report) == 1
    assert "domain module imports rest_framework" in report[0]


def test_the_check_does_not_flag_a_model_field_or_a_read(checker, tmp_path):
    app = tmp_path / "src" / "reservations"
    app.mkdir(parents=True)
    (app / "models.py").write_text(
        "class Reservation:\n"
        "    status = CharField(max_length=20)\n"
        "\n"
        "def render(reservation):\n"
        "    return {'status': reservation.status}\n"
    )

    assert checker.violations(app) == []


@pytest.mark.parametrize(
    "source",
    [
        "def f(r):\n    setattr(r, 'status', 'CONFIRMED')\n",
        "def f(qs, rows):\n    qs.bulk_update(rows, ['status'])\n",
        "def f(qs, rows):\n    qs.bulk_update(rows, fields=('status', 'end_at'))\n",
        "def f(m):\n    m.objects.create(status='CONFIRMED')\n",
        "def f(m):\n    m.objects.update_or_create(id=1, defaults={'status': 'CONFIRMED'})\n",
    ],
)
def test_the_check_detects_indirect_status_writes(checker, tmp_path, source):
    app = tmp_path / "src" / "reservations"
    app.mkdir(parents=True)
    (app / "services.py").write_text(source)

    report = checker.violations(app)

    assert len(report) == 1
    assert "services.py:2" in report[0]


def test_only_the_lifecycle_module_of_the_app_is_exempt(checker, tmp_path):
    app = tmp_path / "src" / "reservations"
    (app / "legacy").mkdir(parents=True)
    (app / "legacy" / "lifecycle.py").write_text("def f(r):\n    r.status = 'CONFIRMED'\n")

    report = checker.violations(app)

    assert len(report) == 1
    assert "legacy/lifecycle.py:2" in report[0]
