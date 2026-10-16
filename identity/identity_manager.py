"""
identity/identity_manager.py

Generación de identidades sintéticas y gestión de perfiles de dispositivos
mixtos (smartphones y tablets) para pruebas, QA y datos de demostración.

- Los correos usan dominios reservados (.test) para que nunca sean reales.
- Los perfiles de dispositivo son descriptores de catálogo (modelo, pantalla,
  SO, user-agent), útiles para pruebas responsive y de compatibilidad.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Optional

from faker import Faker

CHROME_VERSION = "124.0.0.0"

# ---------------------------------------------------------------------------
# Catálogo de dispositivos
# (brand, model, form_factor, os, os_version, width, height, density)
# ---------------------------------------------------------------------------
DEVICE_CATALOG: list[tuple] = [
    # Smartphones Android
    ("Google", "Pixel 8", "smartphone", "Android", "14", 1080, 2400, 2.625),
    ("Samsung", "Galaxy S23", "smartphone", "Android", "14", 1080, 2340, 3.0),
    ("Samsung", "Galaxy A54", "smartphone", "Android", "13", 1080, 2340, 2.625),
    ("Xiaomi", "Redmi Note 12", "smartphone", "Android", "13", 1080, 2400, 2.75),
    ("Motorola", "Moto G73", "smartphone", "Android", "13", 1080, 2400, 2.75),
    # Smartphones iOS
    ("Apple", "iPhone 14", "smartphone", "iOS", "17.4", 1170, 2532, 3.0),
    ("Apple", "iPhone 15 Pro", "smartphone", "iOS", "17.4", 1179, 2556, 3.0),
    # Tablets Android
    ("Samsung", "Galaxy Tab S9", "tablet", "Android", "14", 1600, 2560, 2.0),
    ("Samsung", "Galaxy Tab A8", "tablet", "Android", "13", 1200, 1920, 1.5),
    ("Lenovo", "Tab P11", "tablet", "Android", "13", 1200, 2000, 2.0),
    # Tablets iPadOS
    ("Apple", "iPad (10th gen)", "tablet", "iPadOS", "17.4", 1640, 2360, 2.0),
    ("Apple", "iPad Air (5th gen)", "tablet", "iPadOS", "17.4", 1640, 2360, 2.0),
]

# (locale Faker, país ISO, zona horaria, idioma BCP-47)
LOCALE_CATALOG: list[tuple] = [
    ("es_ES", "ES", "Europe/Madrid", "es-ES"),
    ("es_MX", "MX", "America/Mexico_City", "es-MX"),
    ("es_CO", "CO", "America/Bogota", "es-CO"),
    ("en_US", "US", "America/New_York", "en-US"),
    ("pt_BR", "BR", "America/Sao_Paulo", "pt-BR"),
]


# ---------------------------------------------------------------------------
# Modelos de datos
# ---------------------------------------------------------------------------
@dataclass
class DeviceProfile:
    device_id: str
    form_factor: str  # "smartphone" | "tablet"
    brand: str
    model: str
    os: str
    os_version: str
    screen_width: int
    screen_height: int
    pixel_density: float
    user_agent: str
    language: str
    timezone: str
    fingerprint: str = ""

    def compute_fingerprint(self) -> str:
        """Hash estable (SHA-256) de los atributos del perfil, útil como
        clave de inventario/deduplicación."""
        base = "|".join(
            str(x)
            for x in (
                self.form_factor,
                self.brand,
                self.model,
                self.os,
                self.os_version,
                self.screen_width,
                self.screen_height,
                self.pixel_density,
                self.language,
                self.timezone,
            )
        )
        return hashlib.sha256(base.encode("utf-8")).hexdigest()


@dataclass
class SyntheticIdentity:
    identity_id: str
    full_name: str
    first_name: str
    last_name: str
    username: str
    email: str
    birthdate: str  # ISO 8601, siempre mayor de edad
    country: str
    city: str
    locale: str
    device: DeviceProfile = field(default=None)  # type: ignore[assignment]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SyntheticIdentity":
        dev = DeviceProfile(**data["device"])
        payload = {**data, "device": dev}
        return cls(**payload)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", ".", text.lower()).strip(".")


def _build_user_agent(brand: str, os_name: str, os_version: str,
                      model: str, form_factor: str) -> str:
    if os_name in ("iOS", "iPadOS"):
        device = "iPhone" if form_factor == "smartphone" else "iPad"
        cpu = "iPhone OS" if form_factor == "smartphone" else "OS"
        ver = os_version.replace(".", "_")
        return (
            f"Mozilla/5.0 ({device}; CPU {cpu} {ver} like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 "
            f"{'Mobile/15E148 ' if form_factor == 'smartphone' else ''}"
            "Safari/604.1"
        ).replace("  ", " ")
    mobile = " Mobile" if form_factor == "smartphone" else ""
    return (
        f"Mozilla/5.0 (Linux; Android {os_version}; {model}) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{CHROME_VERSION}{mobile} Safari/537.36"
    )


# ---------------------------------------------------------------------------
# Gestor principal
# ---------------------------------------------------------------------------
class IdentityManager:
    """Genera, almacena y consulta identidades sintéticas con su dispositivo."""

    def __init__(self, storage_path: str | Path = "identity/identities.json",
                 seed: Optional[int] = None):
        self.storage_path = Path(storage_path)
        self._rng = random.Random(seed)
        self._seed = seed
        self._fakers: dict[str, Faker] = {}
        self._identities: dict[str, SyntheticIdentity] = {}
        if self.storage_path.exists():
            self.load()

    # -- generación ---------------------------------------------------------
    def _faker(self, locale: str) -> Faker:
        if locale not in self._fakers:
            f = Faker(locale)
            if self._seed is not None:
                f.seed_instance(self._seed)
            self._fakers[locale] = f
        return self._fakers[locale]

    def _new_id(self) -> str:
        return str(uuid.UUID(int=self._rng.getrandbits(128), version=4))

    def generate_device(self, form_factor: Optional[str] = None,
                        language: str = "es-ES",
                        timezone: str = "Europe/Madrid") -> DeviceProfile:
        pool = [d for d in DEVICE_CATALOG
                if form_factor is None or d[2] == form_factor]
        if not pool:
            raise ValueError(f"form_factor inválido: {form_factor!r}")
        brand, model, ff, os_name, os_ver, w, h, dpr = self._rng.choice(pool)
        device = DeviceProfile(
            device_id=self._new_id(),
            form_factor=ff,
            brand=brand,
            model=model,
            os=os_name,
            os_version=os_ver,
            screen_width=w,
            screen_height=h,
            pixel_density=dpr,
            user_agent=_build_user_agent(brand, os_name, os_ver, model, ff),
            language=language,
            timezone=timezone,
        )
        device.fingerprint = device.compute_fingerprint()
        return device

    def generate_identity(self, form_factor: Optional[str] = None
                          ) -> SyntheticIdentity:
        locale, country, tz, lang = self._rng.choice(LOCALE_CATALOG)
        fake = self._faker(locale)

        first, last = fake.first_name(), fake.last_name()
        slug = f"{_slugify(first)}.{_slugify(last)}"
        suffix = self._rng.randint(10, 9999)

        today = date.today()
        age_days = self._rng.randint(18 * 365, 60 * 365)
        birthdate = today - timedelta(days=age_days)

        identity = SyntheticIdentity(
            identity_id=self._new_id(),
            full_name=f"{first} {last}",
            first_name=first,
            last_name=last,
            username=f"{slug.replace('.', '_')}{suffix}",
            email=f"{slug}{suffix}@example.test",  # dominio reservado (RFC 2606)
            birthdate=birthdate.isoformat(),
            country=country,
            city=fake.city(),
            locale=lang,
            device=self.generate_device(form_factor, lang, tz),
        )
        self._identities[identity.identity_id] = identity
        return identity

    def generate_batch(self, count: int, tablet_ratio: float = 0.3
                       ) -> list[SyntheticIdentity]:
        """Genera `count` identidades con mezcla smartphone/tablet."""
        if not 0.0 <= tablet_ratio <= 1.0:
            raise ValueError("tablet_ratio debe estar entre 0 y 1")
        n_tablets = round(count * tablet_ratio)
        kinds = ["tablet"] * n_tablets + ["smartphone"] * (count - n_tablets)
        self._rng.shuffle(kinds)
        return [self.generate_identity(k) for k in kinds]

    # -- consulta / gestión -------------------------------------------------
    def get(self, identity_id: str) -> Optional[SyntheticIdentity]:
        return self._identities.get(identity_id)

    def list(self, form_factor: Optional[str] = None
             ) -> list[SyntheticIdentity]:
        items: Iterable[SyntheticIdentity] = self._identities.values()
        if form_factor:
            items = (i for i in items if i.device.form_factor == form_factor)
        return list(items)

    def remove(self, identity_id: str) -> bool:
        return self._identities.pop(identity_id, None) is not None

    def stats(self) -> dict:
        items = self.list()
        return {
            "total": len(items),
            "smartphones": sum(i.device.form_factor == "smartphone" for i in items),
            "tablets": sum(i.device.form_factor == "tablet" for i in items),
            "unique_fingerprints": len({i.device.fingerprint for i in items}),
        }

    # -- persistencia -------------------------------------------------------
    def save(self) -> Path:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = [i.to_dict() for i in self._identities.values()]
        self.storage_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self.storage_path

    def load(self) -> None:
        raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
        self._identities = {
            d["identity_id"]: SyntheticIdentity.from_dict(d) for d in raw
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main() -> None:
    p = argparse.ArgumentParser(description="Gestor de identidades sintéticas")
    p.add_argument("-n", "--count", type=int, default=5)
    p.add_argument("--tablet-ratio", type=float, default=0.3)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--out", default="identity/identities.json")
    args = p.parse_args()

    mgr = IdentityManager(storage_path=args.out, seed=args.seed)
    mgr.generate_batch(args.count, args.tablet_ratio)
    path = mgr.save()
    print(json.dumps(mgr.stats(), indent=2))
    print(f"Guardado en: {path}")


if __name__ == "__main__":
    _main()
