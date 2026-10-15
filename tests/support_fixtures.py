"""Shared offline Telegram fixtures; no optional AI SDK dependency."""

from datetime import datetime
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from telegram_intel.config import Config
from telegram_intel.models import Group, Message, UTC
from telegram_intel.store import Store
from telegram_intel.telegram import Gateway


NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
GROUP = Group(-100123, "Research", "research_group", 123, forum=True)


def msg(number, text="BTC bullish research", *, group_id=GROUP.id, sender_id=999, date=NOW, **kwargs):
    return Message(group_id, number, date.isoformat(), text, sender_id, "Alice", "alice", **kwargs)


def raw(number, *, date=NOW, text="BTC", reply=None):
    return SimpleNamespace(id=number, date=date, message=text,
                           sender=SimpleNamespace(first_name="Alice", last_name="Analyst", username="alice"),
                           sender_id=999, reply_to=reply, reactions=None, fwd_from=None, media=None,
                           entities=[], edit_date=None, action=None, grouped_id=None)


class FakeTelegram:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []
        self.connect = AsyncMock()
        self.disconnect = AsyncMock()
        self.is_user_authorized = AsyncMock(return_value=True)
        self.get_me = AsyncMock(return_value=SimpleNamespace(bot=False))

    def iter_messages(self, entity, **kwargs):
        self.calls.append(kwargs)
        items = self.pages.pop(0)
        async def iterator():
            for item in items:
                if isinstance(item, Exception):
                    raise item
                yield item
        return iterator()


class Fixture(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.directory = Path(self.temp.name)
        self.store = Store(self.directory / "cache.sqlite", secure=False)
        self.config = Config(api_id=1, api_hash="fixture-hash-unused", data_dir=self.directory, allow_llm=True,
                             openai_key="fixture-key-unused", batch_tokens=1500)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def gateway(self, pages):
        client = FakeTelegram(pages)
        gateway = Gateway(self.config, self.store, client=client)
        gateway.joined, gateway.entities = [GROUP], {GROUP.id: object()}
        return gateway, client
