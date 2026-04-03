"""Payment plugin — free tier (no-op, for testing and development)."""

from payment_free.plugin import FreeAdapter

__all__ = ["FreeAdapter"]
