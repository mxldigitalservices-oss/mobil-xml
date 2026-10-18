import json
from datetime import date

import pytest

from identity.identity_manager import IdentityManager


def test_seed_does_not_overwrite_existing(tmp_path):
    p = tmp_path / "ids.json"
    a = IdentityManager(p, seed=7, reference_date=date(2026, 1, 1))
    a.generate_batch(20)
    a.save()
    b = IdentityManager(p, seed=7, reference_date=date(2026, 1, 1))
    b.generate_batch(20)
    assert b.stats()["total"] == 40          # antes se pisaban (colisión de IDs)
    assert len({i.username for i in b.list()}) == 40
    assert len({i.email for i in b.list()}) == 40


def test_atomic_save_and_permissions(tmp_path):
    p = tmp_path / "ids.json"
    m = IdentityManager(p, seed=1)
    m.generate_batch(3)
    m.save()
    assert oct(p.stat().st_mode)[-3:] == "600"
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupt_file_gives_clear_error(tmp_path):
    p = tmp_path / "ids.json"
    p.write_text("{no es json")
    with pytest.raises(ValueError, match="corrupto"):
        IdentityManager(p)


def test_unknown_fields_tolerated(tmp_path):
    p = tmp_path / "ids.json"
    m = IdentityManager(p, seed=2)
    m.generate_batch(1)
    m.save()
    data = json.loads(p.read_text())
    data[0]["campo_futuro"] = 1
    data[0]["device"]["otro"] = 2
    p.write_text(json.dumps(data))
    assert IdentityManager(p).stats()["total"] == 1


def test_deterministic_with_reference_date(tmp_path):
    a = IdentityManager(tmp_path / "a.json", seed=3, reference_date=date(2026, 1, 1))
    b = IdentityManager(tmp_path / "b.json", seed=3, reference_date=date(2026, 1, 1))
    assert [i.to_dict() for i in a.generate_batch(5)] == [i.to_dict() for i in b.generate_batch(5)]
