"""LLM Gateway abstraction per Contract 2.2 §5.1 / §6 and Approved Decision 1."""
import os
from typing import Any, Dict, Optional


class LLMGateway:
    """Abstraction for LLM-assisted operations.
    
    Architectural Guarantee: LLM extraction is purely advisory.
    When the LLM provider is offline, unavailable, or unconfigured,
    the system falls back cleanly to an empty draft shipment.
    """
    def __init__(self, provider: str = "mock"):
        self.provider = provider
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")

    def extract_shipment_fields(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Attempt extraction. Returns None if LLM is unavailable or offline."""
        # Check if live extraction is available; if no API key or provider is offline, return None
        if not self.api_key or self.provider == "offline":
            return None

        # When provider is mock or unconfigured, return None per Approved Decision 1:
        # "If the LLM Gateway is unavailable, persist the raw intake and create an empty draft shipment.
        # Do not hardcode successful LLM extraction."
        return None


# Global singleton instance
llm_gateway = LLMGateway(provider="offline")
