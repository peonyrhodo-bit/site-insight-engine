"""In-memory registry for channel/niche identities and historical snapshots."""
from __future__ import annotations

from .opportunity_entities import (
    ChannelSnapshot,
    NicheSnapshot,
    YouTubeChannel,
    YouTubeNiche,
)


class OpportunityDataRegistry:
    def __init__(self) -> None:
        self._channels: dict[str, YouTubeChannel] = {}
        self._channel_snapshots: list[ChannelSnapshot] = []
        self._niches: dict[str, YouTubeNiche] = {}
        self._niche_snapshots: list[NicheSnapshot] = []

    def add_channel(self, channel: YouTubeChannel) -> YouTubeChannel:
        existing = self._channels.get(channel.channel_id)
        if existing is None:
            self._channels[channel.channel_id] = channel
            return channel
        for key, value in channel.to_dict().items():
            if key == "data":
                existing.data.update(value)
            elif value not in (None, ""):
                setattr(existing, key, value)
        return existing

    def add_channel_snapshot(self, snapshot: ChannelSnapshot) -> ChannelSnapshot:
        self._channel_snapshots.append(snapshot)
        return snapshot

    def add_niche(self, niche: YouTubeNiche) -> YouTubeNiche:
        existing = self._niches.get(niche.niche_id)
        if existing is None:
            self._niches[niche.niche_id] = niche
            return niche
        existing.aliases = sorted(set(existing.aliases + niche.aliases))
        if niche.description:
            existing.description = niche.description
        existing.data.update(niche.data)
        return existing

    def add_niche_snapshot(self, snapshot: NicheSnapshot) -> NicheSnapshot:
        self._niche_snapshots.append(snapshot)
        return snapshot

    def channels(self) -> list[YouTubeChannel]:
        return list(self._channels.values())

    def channel_snapshots(self) -> list[ChannelSnapshot]:
        return list(self._channel_snapshots)

    def niches(self) -> list[YouTubeNiche]:
        return list(self._niches.values())

    def niche_snapshots(self) -> list[NicheSnapshot]:
        return list(self._niche_snapshots)

    def clear(self) -> None:
        self._channels.clear()
        self._channel_snapshots.clear()
        self._niches.clear()
        self._niche_snapshots.clear()

    def to_dict(self) -> dict:
        return {
            "channels": [item.to_dict() for item in self.channels()],
            "channel_snapshots": [item.to_dict() for item in self.channel_snapshots()],
            "niches": [item.to_dict() for item in self.niches()],
            "niche_snapshots": [item.to_dict() for item in self.niche_snapshots()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OpportunityDataRegistry":
        registry = cls()
        for item in data.get("channels", []) or []:
            registry.add_channel(YouTubeChannel.from_dict(item))
        for item in data.get("channel_snapshots", []) or []:
            registry.add_channel_snapshot(ChannelSnapshot.from_dict(item))
        for item in data.get("niches", []) or []:
            registry.add_niche(YouTubeNiche.from_dict(item))
        for item in data.get("niche_snapshots", []) or []:
            registry.add_niche_snapshot(NicheSnapshot.from_dict(item))
        return registry

    def counts(self) -> dict[str, int]:
        return {
            "channels": len(self._channels),
            "channel_snapshots": len(self._channel_snapshots),
            "niches": len(self._niches),
            "niche_snapshots": len(self._niche_snapshots),
        }
