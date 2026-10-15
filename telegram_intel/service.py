from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import re

from .config import Config
from .models import UTC
from .preprocess import preprocess
from .report import build_report
from .security import AccountLock, IntelError, prepare_data_directory
from .store import Store
from .telegram import Gateway
from .time_range import parse_datetime, validate_window, window, resolve_window


class Service:
    def __init__(self, config: Config, store: Store, gateway: Gateway, provider=None, notify=None):
        self.config, self.store, self.gateway = config, store, gateway
        self.provider = provider
        self.notify = notify

    def analyzer(self):
        try:
            from .analysis import Analyzer, Provider
        except ModuleNotFoundError as error:
            if error.name == "openai":
                raise IntelError("Optional AI analysis needs the OpenAI SDK. Install requirements-ai.txt or pip install -e '.[ai]'.") from None
            raise
        if self.provider is None:
            self.provider = Provider(self.config)
        return Analyzer(self.config, self.store, self.provider, self.notify)

    async def extract(self, groups: list[str], start: datetime, end: datetime, *, refresh: bool = False,
                      include_reply_context: bool = True):
        """Collect every window message plus separately labeled immediate parents.

        Never apply AI, engagement filtering, content dedup or sender filtering.
        Cached parents are reused unless refresh is requested; inaccessible
        parents are marked unavailable without dropping their child messages.
        """
        from .raw_export import raw_record
        if not groups:
            raise IntelError("Select one or more joined groups.")
        start, end = validate_window(start, end)
        resolved, results = {}, []
        # Resolve all selections before fetching; typo must not silently skip a group.
        for value in groups:
            group = await self.gateway.resolve(value)
            resolved[group.id] = group
        for group in resolved.values():
            if self.notify:
                self.notify(f"Retrieving {group.title} [{start.isoformat()}, {end.isoformat()}).")
            results.append(await self.gateway.get_messages(group, start, end, refresh=refresh))
        messages = {(message.group_id, message.id): message for result in results for message in result.messages}
        parents, contexts, warnings = {}, {}, []
        live_context_failed = False
        for message in messages.values():
            if not message.reply_to:
                continue
            target_group = message.reply_to_group_id if message.reply_to_group_id is not None else message.group_id
            key = (target_group, message.reply_to)
            if key in parents:
                contexts[message.source_id] = parents[key]
                continue
            context = {"source_id": f"{target_group}:{message.reply_to}", "status": "unavailable",
                       "message": None, "within_window": False, "origin": "unavailable"}
            parent = messages.get(key)
            if target_group not in resolved:
                context.update(status="group_not_selected", reason="Reply points to a different group that was not requested; no cross-group retrieval was attempted.")
            elif parent:
                context.update(origin="window", within_window=True)
            elif not include_reply_context:
                context.update(status="not_requested", reason="Outside-window parent retrieval was disabled; reply IDs are preserved.")
            elif not refresh and (parent := self.store.message(*key)):
                context.update(origin="cache")
            elif live_context_failed:
                context.update(status="not_fetched_after_error", reason="Additional parent requests stopped after a Telegram access/rate/network error.")
            else:
                try:
                    parent = await self.gateway.get_message(str(target_group), message.reply_to)
                    if parent:
                        context.update(origin="telegram")
                    else:
                        context["reason"] = "Parent was deleted or is inaccessible to this account."
                except IntelError as error:
                    live_context_failed = True
                    warnings.append("Outside-window reply context is incomplete: " + str(error))
                    context["reason"] = "Telegram could not supply this reply parent; the original child message is preserved."
            if parent:
                context.update(status="available", message={**parent.to_dict(), "group_title": resolved[target_group].title})
            parents[key] = context
            contexts[message.source_id] = context
        rows = [raw_record(message, resolved[message.group_id], self.config.timezone, contexts.get(message.source_id)) for message in messages.values()]
        return results, rows, warnings

    async def export(self, groups: list[str], *, period: str | None = None, start: str | None = None,
                     end: str | None = None, output_dir: str | Path | None = None,
                     format: str = "md", layout: str = "combined", max_messages: int = 1000,
                     max_bytes: int = 2 * 1024 * 1024, refresh: bool = False,
                     include_reply_context: bool = True) -> dict:
        from .raw_export import validate_options, write_bundle
        validate_options(format, layout, max_messages, max_bytes)
        low, high = resolve_window(period=period, start=start, end=end, timezone=self.config.timezone)
        results, rows, warnings = await self.extract(groups, low, high, refresh=refresh, include_reply_context=include_reply_context)
        return write_bundle(results, rows, Path(output_dir) if output_dir else self.config.data_dir / "exports",
                            timezone=self.config.timezone, format=format, layout=layout,
                            max_messages=max_messages, max_bytes=max_bytes, context_warnings=warnings)

    async def summarize(self, groups: list[str], start: datetime, end: datetime, question: str,
                        *, refresh: bool = False, person: str | None = None,
                        previous_report_id: str | None = None) -> dict:
        try:
            from .analysis import Analyzer
        except ModuleNotFoundError as error:
            if error.name == "openai":
                raise IntelError("Optional AI analysis needs requirements-ai.txt or pip install -e '.[ai]'.") from None
            raise
        if not groups:
            raise IntelError("Select one or more joined groups.")
        if not question.strip():
            raise IntelError("Enter a question or summary request.")
        results, seen = [], set()
        for value in groups:
            group = await self.gateway.resolve(value)
            if group.id not in seen:
                seen.add(group.id)
                results.append(await self.gateway.get_messages(group, start, end, refresh=refresh))
        messages = [m for result in results for m in result.messages]
        if person:
            key = person.strip().lstrip("@").casefold()
            # Exact local attribution, never speculative cross-platform matching.
            identities = {m.sender_id for m in messages if key in (m.sender_name.casefold(), (m.sender_username or "").casefold(), str(m.sender_id))}
            if len(identities) > 1:
                raise IntelError("Sender name is ambiguous. Use their exact Telegram username or numeric sender ID.")
            messages = [m for m in messages if key in (m.sender_name.casefold(), (m.sender_username or "").casefold(), str(m.sender_id))]
        previous = self.store.report(previous_report_id) if previous_report_id else None
        prior_topics = [{"rank": i + 1, "title": row["title"], "summary": row["summary"]}
                        for i, row in enumerate(previous["top_discussions"])] if previous else None
        analyzer = self.analyzer() if messages else Analyzer(self.config, self.store, provider=object())
        # Translate volunteered names in the user's question to the same local
        # labels used by preprocessing; no sender roster is sent to OpenAI.
        prepared = preprocess(messages, self.config.expert_ids)
        labels = {occurrence["source_id"]: occurrence["author"] for row in prepared for occurrence in row["occurrences"]}
        question_for_llm = question
        replacements = {}
        for message in messages:
            label = labels.get(message.source_id)
            if label:
                for name in (message.sender_name, message.sender_username):
                    if name and name not in ("Unknown", "Deleted account"):
                        replacements.setdefault(name, set()).add(label)
        for name in sorted(replacements, key=len, reverse=True):
            if len(replacements[name]) == 1:
                question_for_llm = re.sub(r"(?<!\w)@?" + re.escape(name) + r"(?!\w)", next(iter(replacements[name])), question_for_llm, flags=re.I)
        analysis = await analyzer.analyze(question_for_llm, messages, prior_question=previous["question"] if previous else None,
                                         prior_topics=prior_topics)
        report = build_report(question, results, analysis, messages, self.config.timezone, self.config.model, previous_report_id)
        if person:
            report["sender_filter"] = person
            report["limitations"].append("Sender-filtered analysis contains only that sender's posts; interlocutor replies were not analyzed.")
        self.store.save_report(report)
        return report

    async def ask(self, question: str, *, groups: list[str] | None = None,
                  period: str | None = None, start: str | None = None, end: str | None = None,
                  refresh: bool = False, person: str | None = None,
                  previous_report_id: str | None = None) -> dict:
        previous = self.store.report(previous_report_id) if previous_report_id else None
        if previous and not groups:
            groups = [str(r["group"]["id"]) for r in previous["retrieval"]]
        if start or end:
            if not (start and end) or period:
                raise IntelError("Provide --start and --end together, or use --period.")
        if not groups or (not period and not start and not end and not previous):
            catalog = await self.gateway.list_groups()
            plan = await self.analyzer().plan(question, [{"id": str(g.id), "name": g.title, "username": g.username} for g in catalog], datetime.now(UTC),
                                                {"groups": [str(r["group"]["id"]) for r in previous["retrieval"]],
                                                 "start": previous["retrieval"][0]["start"], "end": previous["retrieval"][0]["end"],
                                                 "question": previous["question"]} if previous else None)
            groups = groups or plan.groups
            allowed = {str(g.id) for g in catalog}
            if any(str(value) not in allowed for value in plan.groups):
                raise IntelError("AI selected a group outside the joined catalog. Supply --group explicitly.")
            person = person or plan.person
            if not period and not start and not end:
                period, start, end = plan.period, plan.start, plan.end
                if bool(start) != bool(end) or (period and start):
                    raise IntelError("AI returned an invalid time range. Supply --start/--end or --period explicitly.")
        elif previous:
            groups = groups or [str(r["group"]["id"]) for r in previous["retrieval"]]
        if not start and not period and previous:
            start, end = previous["retrieval"][0]["start"], previous["retrieval"][0]["end"]
        if start and end:
            low, high = validate_window(parse_datetime(start, self.config.timezone), parse_datetime(end, self.config.timezone))
        else:
            low, high = window(period or "72h", timezone=self.config.timezone)
        return await self.summarize(groups or [], low, high, question, refresh=refresh, person=person, previous_report_id=previous_report_id)


@asynccontextmanager
async def open_service(config: Config, *, authenticate: bool = False, notify=None):
    prepare_data_directory(config.data_dir)
    with AccountLock(config.data_dir):
        store = Store(config.data_dir / "messages.sqlite3")
        gateway = Gateway(config, store, notify=notify)
        service = Service(config, store, gateway, notify=notify)
        try:
            await gateway.connect(authenticate=authenticate)
            yield service
        finally:
            try:
                await gateway.disconnect()
                if service.provider:
                    await service.provider.close()
            finally:
                store.close()
