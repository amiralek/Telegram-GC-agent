"""Export participants returned by Telegram for a personal account (Python 3.10+)."""

import argparse
import asyncio
import csv
import getpass
import logging
import os
import re
import sys
import warnings
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, errors, functions, types, utils
from telethon.sessions import MemorySession


FIELDS = ("user_id", "username", "first_name", "last_name")


class ExportError(Exception):
    """An actionable error whose message is safe to display."""


def hidden_input(prompt):
    # Fail closed when the terminal cannot disable echo.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except getpass.GetPassWarning:
            raise ExportError("Use an interactive PowerShell terminal for hidden login prompts.") from None


class FloodBudget:
    def __init__(self, max_wait, retries=5):
        self.max_wait = max_wait
        self.remaining = retries

    async def wait(self, error):
        seconds = max(1, error.seconds)
        if seconds > self.max_wait or self.remaining <= 0:
            raise ExportError(
                f"Telegram requires a {seconds}-second wait. Stopped at the configured "
                "wait/retry limit; try again later."
            ) from None
        self.remaining -= 1
        print(f"Telegram rate limit: waiting {seconds} seconds before retrying.")
        await asyncio.sleep(seconds)

    async def call(self, factory):
        while True:
            try:
                return await factory()
            except errors.FloodWaitError as error:
                await self.wait(error)


async def authenticate(client, budget):
    await client.connect()
    if not await budget.call(client.is_user_authorized):
        phone = os.getenv("TELEGRAM_PHONE") or hidden_input("Telegram phone (+country code): ")
        sent = await budget.call(lambda: client.send_code_request(phone))
        for attempt in range(3):
            code = hidden_input("Telegram login code (hidden): ").strip()
            try:
                await budget.call(lambda: client.sign_in(
                    phone=phone, code=code, phone_code_hash=sent.phone_code_hash
                ))
                break
            except errors.PhoneCodeInvalidError:
                print("Invalid login code. Try again.")
            except errors.PhoneCodeExpiredError:
                raise ExportError("Login code expired. Run the script again for a new code.") from None
            except errors.SessionPasswordNeededError:
                for password_attempt in range(3):
                    password = hidden_input("Telegram two-step verification password (hidden): ")
                    try:
                        await budget.call(lambda: client.sign_in(password=password))
                        break
                    except errors.PasswordHashInvalidError:
                        print("Incorrect two-step verification password. Try again.")
                else:
                    raise ExportError("Authentication failed after three password attempts.")
                break
        else:
            raise ExportError("Authentication failed after three code attempts.")
    me = await budget.call(client.get_me)
    if me is None or me.bot:
        raise ExportError("A personal Telegram account is required; bot accounts are unsupported.")


async def resolve_group(client, target):
    target = target.strip()
    if re.fullmatch(r"-?\d+", target):
        group_id = int(target)
        # Dialogs provide access hashes for private numeric IDs with an in-memory session.
        matches = []
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, (types.Chat, types.Channel)):
                if utils.get_peer_id(entity) == group_id or (group_id > 0 and entity.id == group_id):
                    matches.append(entity)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ExportError("Ambiguous numeric ID. Use the marked negative group ID or username.")
        raise ExportError("Group ID is not in your account's dialogs. Use its username or joined invite link.")

    username, is_invite = utils.parse_username(target)
    if not username:
        raise ExportError("Supply a group username, t.me group/invite link, or numeric group ID.")
    if is_invite:
        invite = await client(functions.messages.CheckChatInviteRequest(username))
        if not isinstance(invite, types.ChatInviteAlready):
            raise ExportError(
                "This account has not joined that private group. Join using Telegram "
                "(and obtain approval if required), then run again."
            )
        return invite.chat
    return await client.get_entity(username)


async def group_metadata(client, entity):
    if isinstance(entity, types.Channel):
        full = (await client(functions.channels.GetFullChannelRequest(entity))).full_chat
        return getattr(full, "participants_count", None), bool(getattr(full, "participants_hidden", False))
    full = (await client(functions.messages.GetFullChatRequest(entity.id))).full_chat
    participants = full.participants
    forbidden = isinstance(participants, types.ChatParticipantsForbidden)
    count = getattr(entity, "participants_count", None)
    if count is None and isinstance(participants, types.ChatParticipants):
        count = len(participants.participants)
    return count, forbidden


async def fetch_bio(client, user, budget):
    try:
        result = await budget.call(lambda: client(functions.users.GetFullUserRequest(user)))
        return getattr(result.full_user, "about", None) or "", False
    except (errors.RPCError, ValueError):
        # A denied/deleted profile must not discard its accessible ID and username.
        return "", True


async def export_participants(client, entity, output, budget, reported_count, restricted, include_bio=False):
    seen = set()
    completed = False
    bio_errors = 0
    # Exclusive creation protects an earlier export from accidental overwriting.
    with output.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS + (("bio",) if include_bio else ()))
        writer.writeheader()
        handle.flush()
        try:
            while True:
                try:
                    async for user in client.iter_participants(entity, limit=None):
                        if user.id in seen:
                            continue
                        row = {
                            "user_id": user.id,
                            "username": user.username or "",
                            "first_name": user.first_name or "",
                            "last_name": user.last_name or "",
                        }
                        try:
                            if include_bio:
                                row["bio"] = ""
                                row["bio"], failed = await fetch_bio(client, user, budget)
                                bio_errors += int(failed)
                                await asyncio.sleep(0.5)
                        finally:
                            # Preserve this member even if bio lookup is interrupted.
                            writer.writerow(row)
                            seen.add(user.id)
                            handle.flush()
                        if len(seen) % 100 == 0:
                            print(f"Exported {len(seen)} members...")
                    completed = True
                    break
                except errors.FloodWaitError as error:
                    await budget.wait(error)
                    # Restart public iteration after an exception; deduplication keeps
                    # rows already exported. No private iterator state is modified.
                except (errors.ChatAdminRequiredError, errors.ChannelPrivateError,
                        errors.ChatForbiddenError, errors.UserNotParticipantError):
                    print("Telegram denied participant enumeration or group access. Accessible rows retained.")
                    break
        finally:
            print(f"Total extracted members: {len(seen)}")
            print(f"Group reported member count: {reported_count if reported_count is not None else 'unavailable'}")
            print(f"CSV saved: {output.resolve()}")
            if include_bio:
                print(f"Bio lookups unavailable: {bio_errors}. Blank bios may also mean no bio is set.")
            if not completed:
                print("Export is partial: enumeration stopped before completion.")
            if restricted or (reported_count is not None and len(seen) < reported_count):
                print("Participant visibility may be restricted, or membership changed during export. "
                      "Only users returned by Telegram were exported.")
            elif reported_count is None:
                print("Completeness cannot be verified: Telegram did not provide a member count.")
    return 0 if completed and not restricted and not bio_errors and (reported_count is None or len(seen) >= reported_count) else 2


async def run(args):
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    try:
        api_id = int(os.environ["TELEGRAM_API_ID"])
        api_hash = os.environ["TELEGRAM_API_HASH"].strip()
        if api_id <= 0 or not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
            raise ValueError
    except (KeyError, ValueError):
        raise ExportError("Set a valid TELEGRAM_API_ID and TELEGRAM_API_HASH in environment variables or .env.") from None
    if args.output.exists():
        raise ExportError("Output already exists. Move it aside or select another path with --output.")
    budget = FloodBudget(args.max_flood_wait)
    client = TelegramClient(MemorySession(), api_id, api_hash,
                            flood_sleep_threshold=0, receive_updates=False,
                            raise_last_call_error=True)
    try:
        await authenticate(client, budget)
        try:
            entity = await budget.call(lambda: resolve_group(client, args.group))
        except ValueError:
            raise ExportError("Could not resolve that group for this account. Check its ID, username, or link.") from None
        if not isinstance(entity, (types.Chat, types.Channel)):
            raise ExportError("The supplied target is not a Telegram group.")
        if isinstance(entity, types.Channel) and not (entity.megagroup or entity.gigagroup):
            raise ExportError("The supplied target is a broadcast channel, not a group.")
        reported_count = getattr(entity, "participants_count", None)
        restricted = False
        try:
            reported_count, restricted = await budget.call(lambda: group_metadata(client, entity))
        except errors.RPCError as error:
            print(f"Member-count metadata unavailable ({type(error).__name__}); trying participant enumeration.")
        return await export_participants(client, entity, args.output, budget, reported_count, restricted, args.include_bio)
    finally:
        await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", help="Username, invite link, or numeric group ID")
    parser.add_argument("--include-bio", action="store_true", help="Fetch accessible bios (one extra API request per member)")
    parser.add_argument("--output", type=Path, default=Path("members.csv"), help="New CSV path (default: members.csv)")
    parser.add_argument("--max-flood-wait", type=int, default=3600, metavar="SECONDS",
                        help="Longest permitted rate-limit wait; at most 5 waits per run (default: 3600)")
    args = parser.parse_args()
    if args.max_flood_wait < 0:
        parser.error("--max-flood-wait must be non-negative")
    # Never print raw Telethon logs, exception payloads, credentials, or codes.
    logging.getLogger("telethon").disabled = True
    logging.getLogger("telethon").setLevel(logging.CRITICAL)
    try:
        return asyncio.run(run(args))
    except ExportError as error:
        print(f"Error: {error}", file=sys.stderr)
    except errors.RPCError as error:
        print(f"Telegram rejected the request ({type(error).__name__}). "
              "Check authentication, group access, invite validity, and account permissions.", file=sys.stderr)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("Stopped. Any rows already written remain in the CSV.", file=sys.stderr)
        return 130
    except (OSError, EOFError):
        print("Network, file, or terminal error. Check connectivity, output path, and terminal access.", file=sys.stderr)
    except Exception as error:
        print(f"Operation failed ({type(error).__name__}). Any rows already written remain in the CSV.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
