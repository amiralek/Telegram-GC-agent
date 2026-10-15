from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


UTC = timezone.utc


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Datetime must have a timezone")
    return value.astimezone(UTC)


def micros(value: datetime) -> int:
    return int(utc(value).timestamp() * 1_000_000)


@dataclass
class Group:
    id: int
    title: str
    username: str | None = None
    channel_id: int | None = None
    forum: bool = False
    broadcast: bool = False
    restriction: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Message:
    group_id: int
    id: int
    date: str
    text: str = ""
    sender_id: int | None = None
    sender_name: str = "Unknown"
    sender_username: str | None = None
    reply_to: int | None = None
    topic_id: int | None = None
    views: int | None = None
    reactions: list[dict] = field(default_factory=list)
    forwarded: dict | None = None
    media: dict | None = None
    urls: list[str] = field(default_factory=list)
    edit_date: str | None = None
    link: str | None = None
    service: str | None = None
    grouped_id: int | None = None
    reply_to_group_id: int | None = None

    @property
    def source_id(self) -> str:
        return f"{self.group_id}:{self.id}"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "source_id": self.source_id}

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(**{k: v for k, v in data.items() if k != "source_id"})


@dataclass
class Retrieval:
    group: Group
    start: str
    end: str
    messages: list[Message]
    complete: bool
    cached: bool
    warnings: list[str]

    def metadata(self) -> dict:
        return {"group": self.group.to_dict(), "start": self.start, "end": self.end,
                "count": len(self.messages), "complete_accessible_history": self.complete,
                "cache_only": self.cached, "warnings": self.warnings,
                "content_is_untrusted": True}
