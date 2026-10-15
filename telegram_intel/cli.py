"""Windows-friendly CLI. Interactive credentials never enter command arguments."""

import argparse
import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
import re
import sys

from . import __version__
from .config import Config, configure
from .preprocess import shared_links
from .report import markdown, save
from .security import AccountLock, IntelError, prepare_directory, prepare_data_directory
from .service import open_service
from .store import Store
from .time_range import resolve_window


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Raw Telegram extraction and local exports; optional AI analysis")
    result.add_argument("--version", action="version", version=f"Telegram GC agent {__version__}")
    result.add_argument("--env-file", type=Path, help="Local .env path (default: current directory/.env, then private app data/.env)")
    sub = result.add_subparsers(dest="command")
    result.set_defaults(command="interactive", ai=False)
    setup = sub.add_parser("configure", help="Save your Telegram API credentials locally using hidden prompts")
    setup.add_argument("--timezone", default="UTC", help="IANA timezone for a new configuration (default UTC)")
    sub.add_parser("auth", help="Authenticate locally with hidden prompts")
    sub.add_parser("groups", help="List joined groups/channels and IDs")
    alias = sub.add_parser("alias", help="Assign a local group alias")
    alias.add_argument("name")
    alias.add_argument("group")
    interactive_parser = sub.add_parser("interactive", help="Select groups/time window and export raw messages (default)")
    interactive_parser.add_argument("--ai", action="store_true", help="Use the original optional OpenAI analysis loop")
    export = sub.add_parser("export", help="Save every accessible message as Markdown/JSON with automatic splitting")
    export.add_argument("--group", action="append", dest="groups", required=True, help="Joined group name, @username, ID or alias; repeat for multiple groups")
    export.add_argument("--period", help="72h, seven days, last 48 hours, yesterday, this week (default 72h)")
    export.add_argument("--start")
    export.add_argument("--end")
    export.add_argument("--format", choices=("md", "json", "both"), default="md")
    export.add_argument("--layout", choices=("combined", "individual"), default="combined")
    export.add_argument("--output-dir", type=Path, help="Parent directory for a fresh export bundle; defaults to private app data/exports")
    export.add_argument("--max-messages", type=int, default=1000, help="Message limit per part; every message remains exported")
    export.add_argument("--max-bytes", type=int, default=2 * 1024 * 1024, help="UTF-8 byte target per data file (default 2 MiB)")
    export.add_argument("--refresh", action="store_true")
    export.add_argument("--no-reply-context", action="store_false", dest="include_reply_context", default=True,
                        help="Skip additional outside-window parent requests; retain in-window context and all reply IDs")
    ask = sub.add_parser("ask", help="Optional OpenAI analysis; requires AI extra, API key and opt-in")
    ask.add_argument("question")
    ask.add_argument("--group", action="append", dest="groups")
    ask.add_argument("--period", help="72h, 7d, yesterday, today, 'this week'")
    ask.add_argument("--start")
    ask.add_argument("--end")
    ask.add_argument("--person", help="Exact Telegram sender name, username or ID, matched locally")
    ask.add_argument("--follow-up", dest="previous_report_id", help="Report ID whose group/window/context to reuse")
    ask.add_argument("--refresh", action="store_true")
    ask.add_argument("--output", type=Path, help="Save Markdown (.md) or JSON (.json)")
    ask.add_argument("--json", action="store_true", help="Print JSON instead of Markdown")
    for name in ("messages", "links"):
        item = sub.add_parser(name, help="Retrieve full accessible history" if name == "messages" else "Extract all shared links without an LLM")
        item.add_argument("group")
        item.add_argument("--period", default=None)
        item.add_argument("--start")
        item.add_argument("--end")
        item.add_argument("--refresh", action="store_true")
        item.add_argument("--output", type=Path, help="Save full JSON; otherwise print JSON")
    purge = sub.add_parser("purge", help="Remove local cache/reports and/or local session; never log out via Telegram")
    purge.add_argument("--cache", action="store_true")
    purge.add_argument("--session", action="store_true")
    purge.add_argument("--yes", action="store_true", help="Confirm local deletion")
    return result


def notify(value: str):
    print(value, file=sys.stderr, flush=True)


def date_args(args, config):
    return resolve_window(period=args.period, start=args.start, end=args.end, timezone=config.timezone)


def show_export(index):
    print(f"Exported {index['message_count']} window messages to {index['directory']}")
    print(f"Index: {index['index_markdown']}")
    for file in index["files"]:
        print(f"{file['path']} ({file['message_count']} messages; {file['bytes']} bytes)")
    if not index["complete_accessible_history"]:
        notify("PARTIAL history: review the index for Telegram retrieval limitations.")
    for warning in index["warnings"]:
        notify(warning)


async def interactive_analysis(service):
    groups = await service.gateway.list_groups()
    if not groups:
        print("No joined groups or subscribed channels were found.")
        return
    for index, group in enumerate(groups, 1):
        print(f"{index}. {group.title} ({group.id})")
    raw = input("Choose group numbers separated by commas: ")
    try:
        choices = [int(x.strip()) for x in raw.split(",")]
        if not choices or any(i < 1 or i > len(groups) for i in choices):
            raise ValueError
        selected = [str(groups[i - 1].id) for i in choices]
    except ValueError:
        raise IntelError("Choose valid group numbers from the displayed list.") from None
    previous = None
    while True:
        question = input("Question (or /groups, /quit): ").strip()
        if question == "/quit":
            break
        if question == "/groups":
            return await interactive_analysis(service)
        if not question:
            continue
        period = input("Time window [72h; blank reuses last window for follow-ups]: ").strip()
        try:
            if not period and previous:
                report = await service.ask(question, groups=selected,
                                           start=previous["retrieval"][0]["start"],
                                           end=previous["retrieval"][0]["end"], previous_report_id=previous["report_id"])
            else:
                report = await service.ask(question, groups=selected, period=period or "72h")
            print(markdown(report))
            default = service.config.data_dir / "reports" / f"{report['report_id']}.md"
            save(report, default)
            save(report, default.with_suffix(".json"))
            print(f"Saved Markdown and JSON in {default.parent}")
            previous = report
        except IntelError as error:
            print(str(error), file=sys.stderr)


async def interactive(service, *, ai: bool = False):
    if ai:
        service.config.require_llm()
        return await interactive_analysis(service)
    while True:
        groups = await service.gateway.list_groups()
        if not groups:
            print("No joined groups or subscribed channels were found.")
            return
        for number, group in enumerate(groups, 1):
            print(f"{number}. {group.title} ({group.id})")
        selected = input("Choose group numbers separated by commas (or /quit): ").strip()
        if selected == "/quit":
            return
        try:
            choices = [int(value.strip()) for value in selected.split(",")]
            if not choices or any(i < 1 or i > len(groups) for i in choices):
                raise ValueError
            selections = [str(groups[i - 1].id) for i in choices]
        except ValueError:
            print("Choose valid group numbers.", file=sys.stderr)
            continue
        while True:
            period = input("Period [72h; e.g. seven days] (or /groups, /quit): ").strip()
            if period == "/quit":
                return
            if period == "/groups":
                break
            format = input("Export format [md / json / both; default md]: ").strip() or "md"
            layout = input("Layout [combined / individual; default combined]: ").strip() or "combined"
            try:
                show_export(await service.export(selections, period=period or "72h", format=format, layout=layout))
            except IntelError as error:
                print(str(error), file=sys.stderr)


def purge(args, config):
    if not args.cache and not args.session:
        raise IntelError("Choose --cache and/or --session.")
    if not args.yes:
        raise IntelError("Local deletion requires --yes. Cache deletion also removes cached reports/checkpoints and default report exports.")
    prepare_data_directory(config.data_dir)
    with AccountLock(config.data_dir):
        if args.cache:
            db = config.data_dir / "messages.sqlite3"
            if db.exists():
                store = Store(db)
                try:
                    store.purge()
                finally:
                    store.close()
                db.unlink()
            reports = config.data_dir / "reports"
            # Only this app's generated report files in its own exact directory.
            if reports.exists() and not reports.is_symlink():
                for path in reports.iterdir():
                    if path.is_file() and path.suffix in (".md", ".json") and re.fullmatch(r"[0-9a-f]{32}", path.stem):
                        path.unlink()
        if args.session:
            for suffix in ("", "-journal", "-wal", "-shm"):
                config.session_path.with_name(config.session_path.name + suffix).unlink(missing_ok=True)
    print("Selected local data removed. Separately saved exports remain at their chosen destinations.")


async def run(args):
    if args.command == "configure":
        path = configure(args.env_file, timezone=args.timezone)
        print(f"Saved private credentials to {path}. Next run: python -m telegram_intel auth")
        return
    config = Config.load(args.env_file, require_telegram=args.command != "purge")
    if args.command == "purge":
        purge(args, config)
        return
    if args.command == "ask":
        config.require_llm()
    async with open_service(config, authenticate=args.command == "auth", notify=notify) as service:
        if args.command == "auth":
            print("Telegram authenticated. Future runs reuse the private local session.")
        elif args.command == "groups":
            for group in await service.gateway.list_groups():
                print(f"{group.id}\t{group.title}\t{'@' + group.username if group.username else ''}\t{'forum' if group.forum else 'channel' if group.broadcast else 'group'}")
        elif args.command == "alias":
            group = await service.gateway.resolve(args.group)
            service.store.set_alias(args.name, group.id)
            print(f"Alias {args.name} -> {group.title} ({group.id})")
        elif args.command == "interactive":
            await interactive(service, ai=args.ai)
        elif args.command == "export":
            index = await service.export(args.groups, period=args.period, start=args.start, end=args.end,
                                         output_dir=args.output_dir, format=args.format, layout=args.layout,
                                         max_messages=args.max_messages, max_bytes=args.max_bytes,
                                         refresh=args.refresh, include_reply_context=args.include_reply_context)
            show_export(index)
        elif args.command == "ask":
            report = await service.ask(args.question, groups=args.groups, period=args.period, start=args.start, end=args.end,
                                       refresh=args.refresh, person=args.person, previous_report_id=args.previous_report_id)
            if args.output:
                save(report, args.output)
                print(f"Saved {args.output.resolve()}")
            else:
                default = config.data_dir / "reports" / f"{report['report_id']}.{'json' if args.json else 'md'}"
                save(report, default)
                print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else markdown(report))
                notify(f"Saved {default}")
        elif args.command in ("messages", "links"):
            low, high = date_args(args, config)
            retrieval = await service.gateway.get_messages(args.group, low, high, refresh=args.refresh)
            payload = {**retrieval.metadata(), "messages": [m.to_dict() for m in retrieval.messages]} if args.command == "messages" else {**retrieval.metadata(), "links": shared_links(retrieval.messages)}
            if args.output:
                # Generic local JSON export using same protected create-before-write policy.
                from .security import protect
                if args.output.suffix.lower() != ".json":
                    raise IntelError("Message/link exports require a .json destination.")
                if not args.output.parent.exists():
                    prepare_directory(args.output.parent)
                try:
                    with args.output.open("x", encoding="utf-8") as handle:
                        protect(args.output)
                        json.dump(payload, handle, ensure_ascii=False, indent=2)
                except FileExistsError:
                    raise IntelError("Output already exists. Choose another filename.") from None
                print(f"Saved {args.output.resolve()}")
            else:
                print(json.dumps(payload, ensure_ascii=False, indent=2))


def main():
    logging.basicConfig(level=logging.CRITICAL)
    args = parser().parse_args()
    try:
        asyncio.run(run(args))
    except IntelError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("Stopped. Cached messages and completed analysis batches are retained.", file=sys.stderr)
        raise SystemExit(130) from None
    except Exception:
        # Avoid raw SDK/network exception strings that can contain secrets/content.
        print("Operation failed. Check configuration, permissions and connectivity. No raw secret-bearing error was printed.", file=sys.stderr)
        raise SystemExit(1) from None
