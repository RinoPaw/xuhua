"""Short-lived references for browser TTS requests.

The browser cannot attach a POST body to an ``<audio>`` source. A ticket keeps
spoken text out of URLs and reverse-proxy access logs while preserving native
streaming playback from a normal GET request.
"""

from __future__ import annotations

from dataclasses import dataclass
import secrets
import time
from typing import Callable


@dataclass(frozen=True, slots=True)
class TtsTicket:
    text: str
    locale: str
    trace_id: str
    segment: int
    reason: str
    client_id: str
    expires_at: float


class TtsTicketCapacity(RuntimeError):
    """The bounded ticket store has no room for another live ticket."""


class TtsTicketStore:
    """Bounded in-memory ticket store owned by one application instance."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 90.0,
        max_entries: int = 512,
        max_per_client: int = 128,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
    ) -> None:
        if ttl_seconds <= 0 or max_entries <= 0 or max_per_client <= 0:
            raise ValueError("TTS ticket limits must be positive")
        if max_per_client > max_entries:
            raise ValueError("per-client TTS ticket limit cannot exceed global capacity")
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = int(max_entries)
        self.max_per_client = int(max_per_client)
        self.clock = clock
        self.token_factory = token_factory
        self._tickets: dict[str, TtsTicket] = {}

    def _prune(self, now: float) -> None:
        for token, ticket in tuple(self._tickets.items()):
            if ticket.expires_at <= now:
                self._tickets.pop(token, None)

    def issue(
        self,
        *,
        text: str,
        locale: str,
        trace_id: str,
        segment: int,
        reason: str,
        client_id: str,
    ) -> str:
        now = self.clock()
        self._prune(now)
        client_key = str(client_id or "unknown").strip()[:256] or "unknown"
        client_count = sum(ticket.client_id == client_key for ticket in self._tickets.values())
        if client_count >= self.max_per_client or len(self._tickets) >= self.max_entries:
            raise TtsTicketCapacity("TTS ticket capacity reached")

        token = self.token_factory()
        while not token or token in self._tickets:
            token = self.token_factory()
        self._tickets[token] = TtsTicket(
            text=text,
            locale=locale,
            trace_id=trace_id,
            segment=segment,
            reason=reason,
            client_id=client_key,
            expires_at=now + self.ttl_seconds,
        )
        return token

    def get(self, token: str) -> TtsTicket | None:
        now = self.clock()
        self._prune(now)
        return self._tickets.get(str(token or ""))

    def __len__(self) -> int:
        self._prune(self.clock())
        return len(self._tickets)


__all__ = ["TtsTicket", "TtsTicketCapacity", "TtsTicketStore"]
