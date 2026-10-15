"""Joined-only history access with a fail-closed MTProto request allowlist."""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta
import logging
import re
from typing import Callable

from telethon import TelegramClient, errors, functions, types, utils

from .config import Config
from .models import Group, Message, Retrieval, UTC, utc
from .security import IntelError, hidden_input, protect
from .store import Store
from .time_range import validate_window


READ_REQUESTS = frozenset({
    functions.users.GetUsersRequest, functions.users.GetFullUserRequest,
    functions.messages.GetDialogsRequest, functions.messages.GetPeerDialogsRequest,
    functions.messages.GetHistoryRequest, functions.messages.GetMessagesRequest,
    functions.messages.GetChatsRequest, functions.messages.GetFullChatRequest,
    functions.channels.GetChannelsRequest, functions.channels.GetFullChannelRequest,
    functions.channels.GetMessagesRequest,
    functions.updates.GetStateRequest, functions.updates.GetDifferenceRequest,
    functions.updates.GetChannelDifferenceRequest,
    functions.help.GetConfigRequest, functions.help.GetNearestDcRequest,
})
AUTH_REQUESTS = frozenset({
    functions.auth.SendCodeRequest, functions.auth.ResendCodeRequest,
    functions.auth.SignInRequest, functions.auth.CheckPasswordRequest,
    functions.account.GetPasswordRequest, functions.auth.ExportAuthorizationRequest,
    functions.auth.ImportAuthorizationRequest,
})
WRAPPERS = (functions.InvokeWithoutUpdatesRequest, functions.InvokeWithLayerRequest,
            functions.InitConnectionRequest, functions.InvokeAfterMsgRequest,
            functions.InvokeAfterMsgsRequest)


def check_request(request, authentication: bool = False) -> None:
    requests = list(request) if utils.is_list_like(request) else [request]
    for item in requests:
        if isinstance(item, WRAPPERS):
            check_request(item.query, authentication)
        elif type(item) not in READ_REQUESTS and not (authentication and type(item) in AUTH_REQUESTS):
            raise IntelError("Blocked a Telegram operation outside the read-only allowlist.")


class ReadOnlyClient(TelegramClient):
    _authentication = False

    @contextmanager
    def authentication(self):
        self._authentication = True
        try:
            yield
        finally:
            self._authentication = False

    async def _call(self, sender, request, ordered=False, flood_sleep_threshold=None):
        check_request(request, self._authentication)
        return await super()._call(sender, request, ordered, flood_sleep_threshold)


class RetryBudget:
    def __init__(self, max_wait: int, notify: Callable[[str], None] | None = None):
        self.max_wait = max_wait
        self.floods = 5
        self.network = 4
        self.notify = notify or (lambda _: None)

    async def pause(self, error: Exception):
        if isinstance(error, (errors.FloodWaitError, errors.FloodPremiumWaitError)):
            seconds = max(1, error.seconds)
            if self.floods <= 0 or seconds > self.max_wait:
                raise IntelError(f"Telegram requires a {seconds}-second wait. Retry later; partial progress is saved.") from None
            self.floods -= 1
            self.notify(f"Telegram rate limit: waiting {seconds} seconds.")
            await asyncio.sleep(seconds)
        elif isinstance(error, (OSError, ConnectionError, asyncio.TimeoutError, errors.ServerError)):
            if self.network <= 0:
                raise IntelError("Telegram connection failed repeatedly. Retry later; partial progress is saved.") from None
            delay = 2 ** (4 - self.network)
            self.network -= 1
            self.notify(f"Telegram connection retry in {delay} seconds.")
            await asyncio.sleep(delay)
        else:
            raise error

    async def call(self, factory):
        while True:
            try:
                return await factory()
            except (errors.FloodWaitError, errors.FloodPremiumWaitError, OSError,
                    ConnectionError, asyncio.TimeoutError, errors.ServerError) as error:
                await self.pause(error)


def message_link(group: Group, message_id: int, topic_id: int | None = None) -> str | None:
    if not group.channel_id or message_id <= 0:
        return None  # Basic chats have no supported permanent message link.
    prefix = f"https://t.me/{group.username}" if group.username and re.fullmatch(r"[A-Za-z0-9_]+", group.username) else f"https://t.me/c/{group.channel_id}"
    topic = f"/{topic_id}" if group.forum and topic_id and topic_id > 0 and topic_id != message_id else ""
    return f"{prefix}{topic}/{message_id}"


def _json_scalar(value):
    if isinstance(value, bytes):
        return None
    if isinstance(value, datetime):
        return utc(value).isoformat()
    if isinstance(value, dict):
        return {k: _json_scalar(v) for k, v in value.items() if k not in ("access_hash", "file_reference", "phone")}
    if isinstance(value, (list, tuple)):
        return [_json_scalar(x) for x in value]
    return value


def record_message(raw, group: Group) -> Message:
    from .preprocess import extract_urls
    sender = getattr(raw, "sender", None)
    name = " ".join(filter(None, (getattr(sender, "first_name", None), getattr(sender, "last_name", None))))
    name = name or getattr(sender, "title", None) or ("Deleted account" if getattr(sender, "deleted", False) else "Unknown")
    reply = getattr(raw, "reply_to", None)
    reply_peer = getattr(reply, "reply_to_peer_id", None)
    topic = (getattr(reply, "reply_to_top_id", None) or getattr(reply, "reply_to_msg_id", None)) if getattr(reply, "forum_topic", False) else None
    action = getattr(raw, "action", None)
    if isinstance(action, types.MessageActionTopicCreate):
        topic = raw.id
    reactions = []
    for result in getattr(getattr(raw, "reactions", None), "results", []) or []:
        reaction = result.reaction
        reactions.append({"reaction": getattr(reaction, "emoticon", None) or
                          str(getattr(reaction, "document_id", "custom")), "count": result.count})
    media = getattr(raw, "media", None)
    media_info = None
    if media:
        media_info = {"type": type(media).__name__}
        webpage = getattr(media, "webpage", None)
        if webpage:
            for attr in ("url", "display_url", "site_name", "title", "description"):
                value = getattr(webpage, attr, None)
                if value:
                    media_info[attr] = value
        file = getattr(raw, "file", None)
        if file:
            for attr in ("name", "mime_type", "size", "duration", "width", "height"):
                value = getattr(file, attr, None)
                if value is not None:
                    media_info[attr] = value
    forward = getattr(raw, "fwd_from", None)
    forward_info = _json_scalar(forward.to_dict()) if forward and hasattr(forward, "to_dict") else None
    text = getattr(raw, "message", "") or ""
    urls = extract_urls(text, getattr(raw, "entities", None) or [])
    if media_info and media_info.get("url"):
        urls = list(dict.fromkeys([*urls, media_info["url"]]))
    return Message(group_id=group.id, id=raw.id, date=utc(raw.date).isoformat(), text=text,
                   sender_id=getattr(raw, "sender_id", None), sender_name=name,
                   sender_username=getattr(sender, "username", None),
                   reply_to=getattr(reply, "reply_to_msg_id", None), topic_id=topic,
                   views=getattr(raw, "views", None), reactions=reactions, forwarded=forward_info,
                   media=media_info, urls=urls,
                   edit_date=utc(raw.edit_date).isoformat() if getattr(raw, "edit_date", None) else None,
                   link=message_link(group, raw.id, topic), service=type(action).__name__ if action else None,
                   grouped_id=getattr(raw, "grouped_id", None),
                   reply_to_group_id=utils.get_peer_id(reply_peer) if reply_peer else None)


class Gateway:
    def __init__(self, config: Config, store: Store, client=None, notify=None):
        self.config, self.store = config, store
        self.budget = RetryBudget(config.max_flood_wait, notify)
        self.entities: dict[int, object] = {}
        self.joined: list[Group] = []
        self.client = client

    def _make_client(self):
        # Fail closed if protecting credentials/session fails. No raw logging.
        if self.config.session_path.is_symlink():
            raise IntelError("Session file must not be a symbolic link.")
        if not self.config.session_path.exists():
            self.config.session_path.touch(mode=0o600)
        protect(self.config.session_path)
        logging.getLogger("telethon").setLevel(logging.CRITICAL)
        client = ReadOnlyClient(str(self.config.session_path), self.config.api_id, self.config.api_hash,
                              receive_updates=False, catch_up=False, flood_sleep_threshold=0,
                              request_retries=2, connection_retries=4, retry_delay=2,
                              auto_reconnect=True, raise_last_call_error=True)
        # Keep authorization/DC state, avoid persisting Telegram entity profiles
        # (which can include phone numbers) inside the session database.
        client.session.save_entities = False
        return client

    async def connect(self, *, authenticate: bool = False):
        if self.client is None:
            self.client = self._make_client()
        try:
            await self.budget.call(self.client.connect)
            authorized = await self.budget.call(self.client.is_user_authorized)
            if not authorized and not authenticate:
                raise IntelError("Authenticate locally first: python -m telegram_intel auth")
            if not authorized:
                await self.authenticate()
            me = await self.budget.call(self.client.get_me)
            if me is None or me.bot:
                raise IntelError("A personal Telegram account is required; bot accounts are unsupported.")
        except errors.RPCError:
            raise IntelError("Telegram could not authorize the session. Check local credentials or run auth again.") from None

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()

    async def authenticate(self):
        phone = hidden_input("Telegram phone (international format; hidden): ").strip()
        if not re.fullmatch(r"\+[1-9]\d{6,14}", phone):
            raise IntelError("Use an international phone number starting with +.")
        with self.client.authentication():
            sent = await self.budget.call(lambda: self.client.send_code_request(phone))
            if isinstance(sent, types.auth.SentCodeSuccess):
                return
            if getattr(sent, "phone_code_hash", None) is None:
                raise IntelError("Telegram did not provide a supported login-code flow. Use an existing account.")
            for attempt in range(3):
                code = hidden_input("Telegram login code (hidden): ").strip().replace(" ", "")
                try:
                    await self.budget.call(lambda: self.client.sign_in(phone=phone, code=code,
                                                                     phone_code_hash=sent.phone_code_hash))
                    return
                except errors.SessionPasswordNeededError:
                    for password_attempt in range(3):
                        password = hidden_input("Telegram 2FA password (hidden): ")
                        try:
                            await self.budget.call(lambda: self.client.sign_in(password=password))
                            return
                        except errors.PasswordHashInvalidError:
                            if password_attempt == 2:
                                raise IntelError("2FA authentication failed. Try auth again later.") from None
                        finally:
                            password = ""
                except errors.PhoneCodeInvalidError:
                    if attempt == 2:
                        raise IntelError("Invalid login code after three attempts. Run auth again.") from None
                except errors.PhoneCodeExpiredError:
                    raise IntelError("Login code expired. Run auth again for a new code.") from None
                finally:
                    code = ""

    async def list_groups(self) -> list[Group]:
        while True:
            entities, groups = {}, []
            try:
                async for dialog in self.client.iter_dialogs(limit=None, ignore_migrated=True):
                    entity = dialog.entity
                    if not (dialog.is_group or dialog.is_channel):
                        continue
                    if getattr(entity, "left", False) or getattr(entity, "kicked", False) or isinstance(entity, (types.ChannelForbidden, types.ChatForbidden)):
                        continue
                    group = Group(id=dialog.id, title=dialog.name or "Untitled",
                                  username=getattr(entity, "username", None),
                                  channel_id=entity.id if isinstance(entity, types.Channel) else None,
                                  forum=bool(getattr(entity, "forum", False)),
                                  broadcast=bool(getattr(entity, "broadcast", False)),
                                  restriction="Telegram reports a content restriction." if getattr(entity, "restriction_reason", None) else None)
                    entities[group.id] = entity
                    groups.append(group)
                self.entities, self.joined = entities, groups
                self.store.save_groups(groups)
                return groups
            except (errors.FloodWaitError, errors.FloodPremiumWaitError, OSError,
                    ConnectionError, asyncio.TimeoutError, errors.ServerError) as error:
                await self.budget.pause(error)
            except errors.RPCError:
                raise IntelError("Telegram denied access to dialogs. Re-authenticate locally if the session expired.") from None

    async def resolve(self, value: str | int) -> Group:
        if not self.joined:
            await self.list_groups()
        raw = str(value).strip()
        alias = self.store.aliases().get(raw.casefold())
        if alias is not None:
            raw = str(alias)
        matches = [g for g in self.joined if raw == str(g.id) or raw.casefold() == g.title.casefold() or
                   (g.username and raw.lstrip("@").casefold() == g.username.casefold())]
        if len(matches) != 1:
            raise IntelError("Group is unavailable or ambiguous. Use a joined group ID from the groups command.")
        return matches[0]

    async def get_messages(self, group: str | int | Group, start_datetime: datetime,
                           end_datetime: datetime, *, refresh: bool = False) -> Retrieval:
        start, end = validate_window(start_datetime, end_datetime)
        group = await self.resolve(group.id if isinstance(group, Group) else group)
        gaps = [(start, end)] if refresh else self.store.missing(group.id, start, end, self.config.cache_ttl)
        warnings = ["Only history visible to this account is included. Deleted, expired or pre-join messages may be unavailable.",
                    "Media contents are not downloaded or transcribed. Cached data may be stale until TTL or --refresh."]
        if group.restriction:
            warnings.append(group.restriction)
        complete = True
        for low, high in gaps:
            self.store.invalidate(group.id, low, high)
            offset = 0
            seen: set[int] = set()
            try:
                while True:
                    try:
                        async for raw in self.client.iter_messages(self.entities[group.id], limit=None,
                                                                  offset_date=high + timedelta(seconds=1),
                                                                  offset_id=offset, wait_time=1):
                            if not getattr(raw, "date", None):
                                continue
                            date = utc(raw.date)
                            if date < low:
                                break
                            if date < high:
                                record = record_message(raw, group)
                                self.store.upsert(record)
                                seen.add(raw.id)
                            offset = raw.id
                        break
                    except (errors.FloodWaitError, errors.FloodPremiumWaitError, OSError,
                            ConnectionError, asyncio.TimeoutError, errors.ServerError) as error:
                        await self.budget.pause(error)
                self.store.reconcile(group.id, low, high, seen)
                self.store.complete(group.id, low, high)
            except IntelError as error:
                complete = False
                warnings.append(str(error))
            except errors.RPCError:
                complete = False
                warnings.append("Telegram denied or interrupted history access. Partial cached messages are included; the window remains incomplete.")
        return Retrieval(group, start.isoformat(), end.isoformat(), self.store.query(group.id, start, end),
                         complete, not gaps, warnings)

    async def get_message(self, group: str | int, message_id: int) -> Message | None:
        if message_id <= 0:
            raise IntelError("Message ID must be positive.")
        resolved = await self.resolve(group)
        try:
            raw = await self.budget.call(lambda: self.client.get_messages(self.entities[resolved.id], ids=message_id))
        except errors.RPCError:
            raise IntelError("Telegram denied access to that message.") from None
        if not raw or isinstance(raw, types.MessageEmpty):
            self.store.remove_message(resolved.id, message_id)
            return None
        record = record_message(raw, resolved)
        self.store.upsert(record)
        return record
