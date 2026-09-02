from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from .io_utils import read_json


def load_model_config(path: Path) -> Dict[str, Any]:
    cfg = read_json(path)
    if not isinstance(cfg, dict):
        raise ValueError(f"Model config must be a JSON object: {path}")
    return cfg


class ChatClient:
    """OpenAI-compatible chat client plus a mock backend for dry runs."""

    def __init__(self, config: Dict[str, Any]):
        self.config = dict(config)
        self.backend = self.config.get("backend", "openai")
        if self.backend == "mock":
            self.config.setdefault("model", "mock")
        elif "model" not in self.config:
            raise ValueError("Model config must contain `model`.")

    def chat(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        if self.backend == "mock":
            return {
                "content": self.config.get("mock_response", ""),
                "reasoning_content": "",
                "finish_reason": "mock",
                "usage": None,
                "raw": {"backend": "mock"},
            }
        return self._chat_openai(messages)

    def _chat_openai(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        api_base = (
            self.config.get("api_base") or self.config.get("base_url") or "https://api.openai.com/v1"
        ).rstrip("/")
        api_key = self.config.get("api_key")
        api_key_env = self.config.get("api_key_env")
        if not api_key and api_key_env:
            api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing API key. Set `{api_key_env}` or put `api_key` in config.")

        payload: Dict[str, Any] = {
            "model": self.config["model"],
            "messages": messages,
            "temperature": self.config.get("temperature", 0),
            "max_tokens": self.config.get("max_tokens", 1200),
        }
        for key in ("top_p", "presence_penalty", "frequency_penalty", "seed", "response_format"):
            if key in self.config:
                payload[key] = self.config[key]

        request = urllib.request.Request(
            api_base + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        retry_count = int(self.config.get("retry_count", 2))
        retry_sleep_seconds = float(self.config.get("retry_sleep_seconds", 1.5))
        timeout_seconds = float(self.config.get("timeout_seconds", 120))
        last_error: Any = None

        for attempt in range(retry_count + 1):
            try:
                with urllib.request.urlopen(request, timeout=timeout_seconds) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                choice = data["choices"][0]
                msg = choice.get("message") or {}
                return {
                    "content": msg.get("content") or "",
                    "reasoning_content": msg.get("reasoning_content") or "",
                    "finish_reason": choice.get("finish_reason"),
                    "usage": data.get("usage"),
                    "response_model": data.get("model"),
                    "response_id": data.get("id"),
                    "raw": data,
                }
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:800]
                last_error = f"HTTP {exc.code}: {detail}"
            except Exception as exc:
                last_error = repr(exc)
            if attempt < retry_count:
                time.sleep(retry_sleep_seconds * (attempt + 1))

        raise RuntimeError(f"Chat completion failed after retries: {last_error}")
