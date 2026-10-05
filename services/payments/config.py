"""Settings are loaded explicitly. Empty configuration never enables payment acceptance."""
import os
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlsplit


@dataclass(frozen=True)
class CodeePayConfig:
    enabled: bool = False
    api_url: str = ''
    api_key: str = field(default='', repr=False)
    webhook_secret: str = field(default='', repr=False)
    merchant_id: str = ''
    timeout_seconds: int = 15

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None):
        env = os.environ if env is None else env
        enabled = env.get('CODEEPAY_ENABLED', 'false').strip().lower()
        if enabled not in {'true', 'false', '1', '0'}:
            raise ValueError('CODEEPAY_ENABLED must be true/false or 1/0')
        timeout = int(env.get('CODEEPAY_TIMEOUT_SECONDS', '15'))
        if not 1 <= timeout <= 60:
            raise ValueError('CODEEPAY_TIMEOUT_SECONDS must be between 1 and 60')
        return cls(enabled=enabled in {'true', '1'}, api_url=env.get('CODEEPAY_API_URL', '').strip(),
                   api_key=env.get('CODEEPAY_API_KEY', ''), webhook_secret=env.get('CODEEPAY_WEBHOOK_SECRET', ''),
                   merchant_id=env.get('CODEEPAY_MERCHANT_ID', '').strip(), timeout_seconds=timeout)

    def validate_checkout_configuration(self) -> None:
        if not self.enabled:
            raise ValueError('codeePay is disabled')
        url = urlsplit(self.api_url)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('CODEEPAY_API_URL must be a clean HTTPS URL')
        if not self.api_key.strip():
            raise ValueError('CODEEPAY_API_KEY is not configured')
