"""Configuration management for Boost.space CLI."""

import json
import os
from pathlib import Path
from typing import Any, Optional

import yaml

try:
    import keyring
except Exception:  # pragma: no cover
    keyring = None


DEFAULT_CONFIG_PATH = Path.home() / ".boostspace-cli" / "config.yaml"
DEFAULT_COOKIE_PATH = Path.home() / ".boostspace-cli" / "cookies.json"
KEYRING_SERVICE = "boostspace-cli"


class Config:
    """Manages CLI configuration and secure secret storage."""

    def __init__(self, config_path: Optional[Path] = None):
        self._path = config_path or DEFAULT_CONFIG_PATH
        self._data: dict[str, Any] = {}
        self._load()
        self._keyring_available = self._check_keyring()

    def _load(self) -> None:
        if self._path.exists():
            with open(self._path, encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self._data, f, default_flow_style=False)

    def _check_keyring(self) -> bool:
        if keyring is None:
            return False
        try:
            keyring.get_password(KEYRING_SERVICE, "_probe_")
            return True
        except Exception:
            return False

    @property
    def secure_storage_enabled(self) -> bool:
        return self._keyring_available

    def _get_secret(self, key: str) -> str:
        if self._keyring_available:
            try:
                secret = keyring.get_password(KEYRING_SERVICE, key) or ""
                if secret:
                    return secret
            except Exception:
                pass
        return self._data.get(key, "")

    def _set_secret(self, key: str, value: str) -> bool:
        if self._keyring_available:
            try:
                if value:
                    keyring.set_password(KEYRING_SERVICE, key, value)
                else:
                    try:
                        keyring.delete_password(KEYRING_SERVICE, key)
                    except Exception:
                        pass
                if key in self._data:
                    del self._data[key]
                    self._save()
                return True
            except Exception:
                pass

        self._data[key] = value
        self._save()
        return False

    @property
    def backend(self) -> str:
        return self._data.get("backend", "boostspace")

    @backend.setter
    def backend(self, value: str) -> None:
        self._data["backend"] = value
        self._save()

    @property
    def zone_url(self) -> str:
        return os.getenv("BOOST_ZONE_URL") or self._data.get("zone_url", "https://eu1.make.com")

    @zone_url.setter
    def zone_url(self, value: str) -> None:
        self._data["zone_url"] = value
        self._save()

    @property
    def organization_id(self) -> Optional[int]:
        env_val = os.getenv("BOOST_ORGANIZATION_ID")
        if env_val:
            return int(env_val)
        val = self._data.get("organization_id")
        return int(val) if val else None

    @organization_id.setter
    def organization_id(self, value: Optional[int]) -> None:
        self._data["organization_id"] = value
        self._save()

    @property
    def team_id(self) -> Optional[int]:
        env_val = os.getenv("BOOST_TEAM_ID")
        if env_val:
            return int(env_val)
        val = self._data.get("team_id")
        return int(val) if val else None

    @team_id.setter
    def team_id(self, value: Optional[int]) -> None:
        self._data["team_id"] = value
        self._save()

    @property
    def base_url(self) -> str:
        if self.backend == "boostspace":
            return "https://integrator.boost.space/api/v2"
        return f"{self.zone_url}/api/v2"

    @property
    def sso_url(self) -> str:
        if self.backend == "boostspace":
            return "https://integrator.boost.space/sso/oauth"
        return f"{self.zone_url}/sso/oauth"

    @property
    def token_url(self) -> str:
        override = self.oauth_token_url
        if override:
            return override
        if self.backend == "boostspace":
            return "https://integrator.boost.space/oauth/token"
        return f"{self.zone_url}/oauth/token"

    @property
    def oauth_token(self) -> str:
        return os.getenv("BOOST_OAUTH_TOKEN", "") or self._get_secret("oauth_token")

    @oauth_token.setter
    def oauth_token(self, value: str) -> None:
        self._set_secret("oauth_token", value)

    @property
    def oauth_refresh_token(self) -> str:
        return os.getenv("BOOST_OAUTH_REFRESH_TOKEN", "") or self._get_secret("oauth_refresh_token")

    @oauth_refresh_token.setter
    def oauth_refresh_token(self, value: str) -> None:
        self._set_secret("oauth_refresh_token", value)

    @property
    def oauth_token_expires_at(self) -> Optional[float]:
        val = self._data.get("oauth_token_expires_at")
        return float(val) if val else None

    @oauth_token_expires_at.setter
    def oauth_token_expires_at(self, value: Optional[float]) -> None:
        self._data["oauth_token_expires_at"] = value
        self._save()

    @property
    def oauth_client_id(self) -> str:
        return self._data.get("oauth_client_id", "1")

    @oauth_client_id.setter
    def oauth_client_id(self, value: str) -> None:
        self._data["oauth_client_id"] = value
        self._save()

    @property
    def oauth_token_url(self) -> str:
        return self._data.get("oauth_token_url", "")

    @oauth_token_url.setter
    def oauth_token_url(self, value: str) -> None:
        self._data["oauth_token_url"] = value
        self._save()

    @property
    def cookie_path(self) -> Path:
        return DEFAULT_COOKIE_PATH

    def load_cookies(self) -> Optional[list[dict[str, Any]]]:
        env_json = os.getenv("BOOST_COOKIES_JSON", "")
        if env_json:
            try:
                return json.loads(env_json)
            except json.JSONDecodeError:
                return None

        secret = self._get_secret("cookies_json")
        if secret:
            try:
                return json.loads(secret)
            except json.JSONDecodeError:
                pass

        if self.cookie_path.exists():
            with open(self.cookie_path, encoding="utf-8") as f:
                return json.load(f)

        return None

    def save_cookies(self, cookies: list[dict[str, Any]]) -> None:
        payload = json.dumps(cookies)
        stored_in_keyring = self._set_secret("cookies_json", payload)

        if not stored_in_keyring:
            self.cookie_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cookie_path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)
        elif self.cookie_path.exists():
            self.cookie_path.unlink()

    def has_cookies(self) -> bool:
        cookies = self.load_cookies()
        return bool(cookies)

    def clear_cookies(self) -> None:
        self._set_secret("cookies_json", "")
        if self.cookie_path.exists():
            self.cookie_path.unlink()

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._save()

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)
