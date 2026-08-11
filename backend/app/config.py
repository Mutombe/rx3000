import os
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


class Settings:
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./rx3000.db")

    PHARMACY_NAME: str = os.getenv("PHARMACY_NAME", "RX3000 Pharmacy")
    PHARMACY_REG_NO: str = os.getenv("PHARMACY_REG_NO", "Y123456")

    # Which regulatory pack this installation runs under (see jurisdictions.py).
    # VAT and currency default to the pack; set them only to override it.
    JURISDICTION: str = os.getenv("JURISDICTION", "ZA")
    _VAT_OVERRIDE: str = os.getenv("VAT_RATE", "")
    _CURRENCY_OVERRIDE: str = os.getenv("CURRENCY", "")

    # development | production. Simulators are the default everywhere because
    # they let the whole system be built and demonstrated before any merchant
    # agreement exists — but a pharmacy running live on a simulator would be
    # approving fake adjudications and filing nothing with the revenue
    # authority. In production every simulator refuses to act. See integrations.py.
    ENVIRONMENT: str = os.getenv("RX3000_ENV", "development")

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
