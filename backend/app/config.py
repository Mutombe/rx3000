import os
import sys
from pathlib import Path

# Minimal .env loader (no external dependency)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def env(name: str, default: str = "") -> str:
    """Read RX5000_<name>, falling back to the RX3000_<name> it used to be.

    The product was renamed. Every pharmacy that already runs this has RX3000_*
    variables in a .env file, a systemd unit or a Render dashboard, and a rename
    that only accepted the new spelling would silently revert each of them to a
    default — RX3000_ENV=production quietly becoming development, a licence key
    quietly becoming absent. Reading both costs nothing and breaks nobody; new
    installations only ever see the new name.
    """
    value = os.getenv("RX5000_" + name)
    if value is None:
        value = os.getenv("RX3000_" + name)
    return default if value is None else value


def _data_dir() -> Path:
    """Where a pharmacy's own data lives.

    Running from a source checkout this is `backend/`, which is what every
    developer and every existing install already expects.

    Running as the executable bundled inside the desktop app it cannot be:
    that lives in `Program Files`, which is read-only for the person at the
    till, and a database that cannot be written is a pharmacy that cannot
    dispense. So a frozen build keeps its data in the per-user application
    data directory instead, which is also where a backup tool would look for
    it and where it survives reinstalling the app.
    """
    override = env("DATA_DIR")
    if override:
        return Path(override).expanduser()

    if getattr(sys, "frozen", False):          # PyInstaller
        if sys.platform == "win32":
            base = Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming")
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        return base / "RX5000"

    return Path(__file__).resolve().parent.parent


def _default_database_url() -> str:
    """Prefer rx5000.db, but adopt an existing rx3000.db rather than ignore it.

    Defaulting straight to the new filename would start a pharmacy on an empty
    database while their real one sat in the same folder — the data is not lost,
    but it is gone from their point of view, which is the same emergency.
    """
    here = _data_dir()
    here.mkdir(parents=True, exist_ok=True)
    legacy = here / "rx3000.db"
    if legacy.exists() and not (here / "rx5000.db").exists():
        return f"sqlite:///{(here / 'rx3000.db').as_posix()}"
    return f"sqlite:///{(here / 'rx5000.db').as_posix()}"


class Settings:
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    DATABASE_URL: str = os.getenv("DATABASE_URL") or _default_database_url()
    # Whether an empty deployment loads the demonstration pharmacy on first boot.
    # On for the hosted demo, and the first thing a real pharmacy turns off:
    # nobody wants a hundred and eighty invented patients in their register.
    SEED_DEMO_DATA: bool = os.getenv("SEED_DEMO_DATA", "1") not in ("0", "false", "False")

    PHARMACY_NAME: str = os.getenv("PHARMACY_NAME", "RX5000 Pharmacy")
    PHARMACY_REG_NO: str = os.getenv("PHARMACY_REG_NO", "Y123456")
    # Printed at the foot of every dispensing label. A patient holding a box of
    # tablets and a question needs the address and the number on the sticker,
    # not in a system somebody else can log into.
    PHARMACY_ADDRESS: str = os.getenv("PHARMACY_ADDRESS", "")
    PHARMACY_PHONE: str = os.getenv("PHARMACY_PHONE", "")

    # Which regulatory pack this installation runs under (see jurisdictions.py).
    # VAT and currency default to the pack; set them only to override it.
    JURISDICTION: str = os.getenv("JURISDICTION", "ZW")
    _VAT_OVERRIDE: str = os.getenv("VAT_RATE", "")
    _CURRENCY_OVERRIDE: str = os.getenv("CURRENCY", "")

    # development | production. Simulators are the default everywhere because
    # they let the whole system be built and demonstrated before any merchant
    # agreement exists — but a pharmacy running live on a simulator would be
    # approving fake adjudications and filing nothing with the revenue
    # authority. In production every simulator refuses to act. See integrations.py.
    ENVIRONMENT: str = env("ENV", "development")

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() in ("production", "prod", "live")

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", "pharmacy@example.com")

    SMS_GATEWAY_URL: str = os.getenv("SMS_GATEWAY_URL", "")

    TOKEN_TTL_HOURS: int = 12

    @property
    def jurisdiction(self):
        from . import jurisdictions
        return jurisdictions.get(self.JURISDICTION)

    @property
    def VAT_RATE(self) -> float:
        return float(self._VAT_OVERRIDE) if self._VAT_OVERRIDE else self.jurisdiction.vat_rate

    @property
    def CURRENCY(self) -> str:
        return self._CURRENCY_OVERRIDE or self.jurisdiction.base_currency.symbol


settings = Settings()
