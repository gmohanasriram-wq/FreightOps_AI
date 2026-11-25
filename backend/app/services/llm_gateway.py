"""LLM Gateway abstraction per Contract 2.2 §5.1 / §6 and Approved Decision 1.

Extraction is advisory only: when no provider is configured the intake service
persists the raw submission and an empty draft shipment. Explanation narration
is always optional; the deterministic template is authoritative and is never
replaced by an unverified claim.

Demo mode (``LLM_DEMO_MODE=true``) never contacts an external provider, so the
application is deterministic and free to run without an API key. When demo mode
is disabled and a provider plus key are configured, narration is requested with
a strict "paraphrase only" instruction and any failure falls back to the
deterministic template.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from backend.app.core.config import settings

NARRATION_SYSTEM_PROMPT = (
    "You are a freight brokerage operations assistant. Rewrite the supplied "
    "verified facts as one short paragraph for a broker. Use ONLY the facts in "
    "the input. Do not add numbers, rates, carrier performance history, "
    "reliability, on-time statistics, recommendations, or any claim that is not "
    "explicitly present. If a fact is absent, omit it rather than guessing."
)


@dataclass(frozen=True)
class NarrationResult:
    narration: Optional[str]
    provider: str
    model_identifier: Optional[str]
    latency_ms: int
    status: str
    error_code: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.status == "success" and bool(self.narration)


class LLMGateway:
    """Abstraction for LLM-assisted operations."""

    def __init__(self, provider: Optional[str] = None):
        self.provider = (provider or settings.LLM_PROVIDER or "offline").lower()
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        self.base_url = settings.LLM_BASE_URL
        self.timeout = settings.LLM_TIMEOUT_SECONDS
        self.max_retries = settings.LLM_MAX_RETRIES
        self.demo_mode = settings.LLM_DEMO_MODE

    # ------------------------------------------------------------------
    # Extraction (advisory)
    # ------------------------------------------------------------------
    def extract_shipment_fields(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Attempt extraction. Returns None if the LLM is unavailable or offline."""
        if not self.api_key or self.provider == "offline":
            return None

        # Approved Decision 1: never fabricate a successful extraction when the
        # provider is not actually reachable/configured.
        return None

    # ------------------------------------------------------------------
    # Explanation narration
    # ------------------------------------------------------------------
    def narrate_explanation(self, facts: str) -> NarrationResult:
        """Request an optional paraphrase of verified facts.

        Never raises: every failure is reported in the result so the workflow can
        continue with the deterministic template.
        """
        started = time.monotonic()
        model = self.model if self.provider in ("openai", "gemini") else None

        def failure(code: str) -> NarrationResult:
            return NarrationResult(
                narration=None,
                provider=self.provider,
                model_identifier=model,
                latency_ms=int((time.monotonic() - started) * 1000),
                status="error",
                error_code=code,
            )

        if self.provider in ("", "offline"):
            return failure("LLM_OFFLINE")
        if self.provider not in ("openai", "gemini"):
            return failure("LLM_PROVIDER_UNSUPPORTED")
        if not self.api_key:
            return failure("LLM_NOT_CONFIGURED")
        if self.demo_mode:
            # Deliberately no network call in demo mode.
            return failure("LLM_DEMO_MODE")

        last_error = "LLM_CALL_FAILED"
        for attempt in range(max(0, self.max_retries) + 1):
            try:
                text = self._call_provider(facts)
            except httpx.TimeoutException:
                last_error = "LLM_TIMEOUT"
                continue
            except Exception:  # noqa: BLE001 - never leak provider details
                last_error = "LLM_CALL_FAILED"
                continue

            if not text or not text.strip():
                last_error = "LLM_EMPTY_RESPONSE"
                continue
            cleaned = " ".join(text.split()).strip()
            if len(cleaned) > 4000:
                cleaned = cleaned[:4000]
            return NarrationResult(
                narration=cleaned,
                provider=self.provider,
                model_identifier=model,
                latency_ms=int((time.monotonic() - started) * 1000),
                status="success",
            )

        return failure(last_error)

    def _call_provider(self, facts: str) -> str:
        if self.provider == "openai":
            base = (self.base_url or "https://api.openai.com/v1").rstrip("/")
            response = httpx.post(
                f"{base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": NARRATION_SYSTEM_PROMPT},
                        {"role": "user", "content": facts},
                    ],
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            return payload["choices"][0]["message"]["content"]

        base = (self.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        response = httpx.post(
            f"{base}/models/{self.model}:generateContent",
            params={"key": self.api_key},
            headers={"Content-Type": "application/json"},
            json={
                "systemInstruction": {"parts": [{"text": NARRATION_SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": facts}]}],
                "generationConfig": {"temperature": 0},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        parts = payload["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts)


# Global singleton instance. Settings drive the provider; the default is offline.
llm_gateway = LLMGateway()
