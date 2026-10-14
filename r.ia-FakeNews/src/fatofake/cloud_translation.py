"""Cliente mínimo para Cloud Translation Basic v2."""

from __future__ import annotations

from html import unescape
from typing import Callable

import requests


class TranslationError(RuntimeError):
    pass


class GoogleCloudTranslator:
    endpoint = "https://translation.googleapis.com/language/translate/v2"

    def __init__(self, api_key: str, *, timeout: float = 30.0,
                 post: Callable | None = None) -> None:
        if not api_key.strip():
            raise ValueError("A chave do Cloud Translation não pode estar vazia.")
        self.api_key = api_key
        self.timeout = timeout
        self._post = post or requests.post

    def translate(self, texts: list[str], *, target: str = "pt") -> list[str]:
        if not texts:
            return []
        translated = []
        for offset in range(0, len(texts), 128):
            batch = texts[offset:offset + 128]
            try:
                response = self._post(
                    self.endpoint,
                    headers={"x-goog-api-key": self.api_key},
                    json={"q": batch, "target": target, "format": "text"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                items = response.json().get("data", {}).get("translations", [])
            except (requests.RequestException, ValueError, AttributeError) as error:
                raise TranslationError("O Cloud Translation não respondeu corretamente.") from error
            values = [unescape(str(item.get("translatedText") or "")).strip() for item in items]
            if len(values) != len(batch) or any(not value for value in values):
                raise TranslationError("O Cloud Translation retornou uma tradução incompleta.")
            translated.extend(values)
        return translated
