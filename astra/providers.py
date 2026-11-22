"""Secure local configuration and OpenAI-compatible chat provider.

The provider is optional: indexing and context retrieval never depend on it.
Secrets are kept server-side, never returned by the settings API, and written
with owner-only permissions where the platform supports POSIX modes.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class ProviderConfigurationError(ValueError):
    """Invalid provider configuration."""


class ProviderRequestError(RuntimeError):
    """A provider request failed without exposing credentials."""


@dataclass(frozen=True)
class ProviderConfig:
    provider: str = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.model.strip() and self.base_url.strip())


def validate_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ProviderConfigurationError("base_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderConfigurationError("base_url cannot contain credentials, query, or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {
        "localhost", "127.0.0.1", "::1"
    }:
        raise ProviderConfigurationError("plain HTTP is allowed only for localhost providers")
    if parsed.path.endswith("/chat/completions"):
        value = value[: -len("/chat/completions")]
    return value


class ProviderConfigStore:
    """Atomic, versioned configuration stored under ASTRA_HOME."""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        home = Path(os.environ.get("ASTRA_HOME", Path.home() / ".astra"))
        self.path = Path(path) if path else home / "providers.json"

    def load(self) -> ProviderConfig:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("version") != 1:
                raise ProviderConfigurationError("unsupported provider config version")
            config = ProviderConfig(
                provider=str(raw.get("provider", "openai-compatible")),
                base_url=validate_base_url(str(raw.get("base_url", "https://api.openai.com/v1"))),
                model=str(raw.get("model", "gpt-4o-mini")).strip(),
                api_key=str(raw.get("api_key", "")),
            )
        except FileNotFoundError:
            config = ProviderConfig()
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise ProviderConfigurationError(f"could not read provider settings: {exc}") from exc

        # Explicit environment variables override the local settings file.
        return ProviderConfig(
            provider=os.environ.get("ASTRA_PROVIDER", config.provider),
            base_url=validate_base_url(os.environ.get("ASTRA_BASE_URL", config.base_url)),
            model=os.environ.get("ASTRA_MODEL", config.model).strip(),
            api_key=os.environ.get("ASTRA_API_KEY", config.api_key),
        )

    def save(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        api_key: str | None,
        clear_api_key: bool = False,
    ) -> ProviderConfig:
        if provider != "openai-compatible":
            raise ProviderConfigurationError("only the OpenAI-compatible chat API is supported")
        normalized_url = validate_base_url(base_url)
        model = model.strip()
        if not model or len(model) > 200:
            raise ProviderConfigurationError("model must contain 1–200 characters")
        if len(normalized_url) > 500:
            raise ProviderConfigurationError("base_url is too long")
        current = self.load()
        secret = "" if clear_api_key else (
            current.api_key if api_key is None or api_key == "" else api_key.strip()
        )
        if len(secret) > 4096:
            raise ProviderConfigurationError("API key is too long")

        config = ProviderConfig(provider, normalized_url, model, secret)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=".providers-", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "version": 1,
                        "provider": config.provider,
                        "base_url": config.base_url,
                        "model": config.model,
                        "api_key": config.api_key,
                    },
                    stream,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return config

    @staticmethod
    def public_view(config: ProviderConfig) -> dict:
        return {
            "provider": config.provider,
            "base_url": config.base_url,
            "model": config.model,
            "configured": config.configured,
            "key_present": bool(config.api_key),
        }


class OpenAICompatibleProvider:
    """Small synchronous chat-completions client using only the stdlib."""

    def __init__(self, config: ProviderConfig, timeout: float = 90.0):
        self.config = config
        self.timeout = timeout

    def __call__(self, prompt: str) -> str:
        if not self.config.configured:
            raise ProviderConfigurationError("provider is not configured")
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a careful repository engineering assistant. "
                        "Return only the requested JSON edit object. Never claim "
                        "to have applied changes."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    raise ProviderRequestError("provider response exceeded 1 MiB")
                body = json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            # Do not forward provider response bodies: they can contain prompt
            # fragments or request metadata. Credentials are never logged.
            raise ProviderRequestError(
                f"provider returned HTTP {exc.code}"
            ) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderRequestError(
                f"provider connection failed: {type(exc).__name__}"
            ) from None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderRequestError("provider returned invalid JSON") from None

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderRequestError("provider response did not contain a chat completion") from None
        if not isinstance(content, str) or not content.strip():
            raise ProviderRequestError("provider returned an empty completion")
        return content
