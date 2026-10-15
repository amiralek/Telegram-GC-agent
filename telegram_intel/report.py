"""Render author/time/links from local records, never model-generated identities."""

from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from .models import Message, Retrieval, UTC
from .preprocess import entities, shared_links
from .security import IntelError, prepare_directory, protect


def build_report(question: str, results: list[Retrieval], analysis: dict, messages: list[Message],
                 timezone: str, model: str, previous_report_id: str | None = None) -> dict:
    from .analysis import claim_iter
    sources = {}
    names = {result.group.id: result.group.title for result in results}
    for message in messages:
        sources[message.source_id] = {"group": names.get(message.group_id, str(message.group_id)),
                                      "group_id": message.group_id, "message_id": message.id,
                                      "author": message.sender_name, "sender_id": message.sender_id,
                                      "username": message.sender_username, "time_utc": message.date,
                                      "time_local": datetime.fromisoformat(message.date).astimezone(ZoneInfo(timezone)).isoformat(),
                                      "link": message.link, "reply_to": message.reply_to,
                                      "topic_id": message.topic_id, "forwarded": bool(message.forwarded),
                                      "media": message.media}
    # Attach participants to findings using cited evidence, not model guesses.
    for category in ("top_discussions", "high_signal_messages", "crypto_intelligence", "actionable_takeaways"):
        for finding in analysis["draft"][category]:
            refs = list(dict.fromkeys(sid for claim in claim_iter(finding) for sid in claim["source_ids"]))
            finding["sources"] = [sources[sid] for sid in refs]
            finding["participants"] = list(dict.fromkeys(sources[sid]["author"] for sid in refs))
    entity_index = {"tickers": {}, "addresses": {}, "protocols": {}}
    for message in messages:
        for kind, values in entities(message.text).items():
            for value in values:
                entity_index[kind].setdefault(value, []).append(message.source_id)
    return {"report_id": uuid4().hex, "created_at": datetime.now(UTC).isoformat(), "question": question,
            "previous_report_id": previous_report_id, "timezone": timezone, "model": model,
            "retrieval": [r.metadata() for r in results], "message_count": len(messages),
            "complete_accessible_history": all(r.complete for r in results),
            "content_is_untrusted": True,
            "claim_policy": "Observations describe the messages; trading assertions are attributed opinions/speculation/unverified. No external fact checking was performed.",
            "privacy": "Selected text was sent to OpenAI with participant pseudonyms and basic phone/email redaction. Text itself may identify people. Empty periods use no synthesis call.",
            **analysis["draft"], "links_shared": shared_links(messages), "detected_entities": entity_index,
            "sources": sources,
            "analysis_metadata": {key: analysis[key] for key in ("analysis_batches", "analyzed_source_count", "distinct_content_count")},
            "batch_findings": analysis["batch_findings"], "preprocessing": analysis["preprocessing"]}


def plain(value: str) -> str:
    # Escape literal untrusted text so names and prose cannot embed HTML/images.
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("[", "\\[").replace("]", "\\]").replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")


def markdown(report: dict) -> str:
    sources = report["sources"]

    def refs(ids):
        parts = []
        for sid in dict.fromkeys(ids):
            source = sources.get(sid)
            if not source:
                continue
            label = plain(f"{source['author']} · {source['group']} · {source['time_local']} · #{source['message_id']}")
            parts.append(f"[{label}]({source['link']})" if source["link"] else f"{label} (no supported message link)")
        return "; ".join(parts)

    def claim(row):
        return f"{plain(row['text'])} **[{row['kind']}]**\n\nSources: {refs(row['source_ids'])}"

    lines = ["# Telegram intelligence briefing", "", f"Question: {plain(report['question'])}", "",
             f"Report ID: `{report['report_id']}` · {report['message_count']} messages · timezone {report['timezone']}", "",
             "## Coverage and limitations", "", report["claim_policy"], ""]
    for result in report["retrieval"]:
        status = "complete traversal of accessible history" if result["complete_accessible_history"] else "PARTIAL history"
        lines += [f"- {plain(result['group']['title'])}: {result['count']} messages, {result['start']} to {result['end']}; {status}."]
        lines += [f"- {plain(warning)}" for warning in result["warnings"]]
    lines += ["", "## Executive summary", ""]
    lines += [claim(row) + "\n" for row in report["executive_summary"]]
    if not report["executive_summary"]:
        lines += ["No supported summary is available for this period/filter.", ""]
    categories = [("Top discussions", "top_discussions"), ("High-signal messages", "high_signal_messages"),
                  ("Trading and crypto intelligence", "crypto_intelligence"), ("Actionable takeaways", "actionable_takeaways")]
    for title, key in categories:
        lines += [f"## {title}", ""]
        for index, finding in enumerate(report[key], 1):
            lines += [f"### {index}. {plain(finding['title'])}", "",
                      f"Importance: {finding['importance']} · Sentiment: {finding['sentiment']} · Minority view: {finding['minority_view']}", "",
                      claim(finding["summary"]), "", "Why it matters: " + claim(finding["why_it_matters"]), ""]
            if finding.get("participants"):
                lines += ["Participants in cited evidence: " + ", ".join(plain(x) for x in finding["participants"]), ""]
            for heading, field in (("Arguments", "arguments"), ("Counterarguments / risks", "counterarguments")):
                if finding[field]:
                    lines += [f"**{heading}**", ""]
                    lines += [claim(row) + "\n" for row in finding[field]]
        if not report[key]:
            lines += ["No supported findings in this category.", ""]
    lines += ["## Links shared", "", "Links are untrusted, classified heuristically and have not been opened or verified.", ""]
    for category in ("X/Twitter discussions", "Research articles", "Protocol websites and documentation", "Trading tools, dashboards, and charts", "Other resources"):
        rows = [row for row in report["links_shared"] if row["category"] == category]
        if not rows:
            continue
        lines += [f"### {category}", ""]
        for row in rows:
            # Angle-bracket destination preserves parentheses in valid HTTP URLs.
            safe = row["url"].replace("<", "%3C").replace(">", "%3E")
            lines += [f"- [{plain(row['url'])}](<{safe}>)"]
            for context in row["contexts"]:
                lines += [f"  - Context: {plain(context['text'])}", f"    Source: {refs([context['source_id']])}"]
        lines.append("")
    lines += ["## Detected tickers, address candidates and protocols", "",
              "Ticker/address detection is heuristic; a matching string does not verify a token or contract.", ""]
    for category, values in report["detected_entities"].items():
        for value, ids in values.items():
            lines += [f"- {category}: {plain(value)} — {refs(ids)}"]
    lines += ["", "## Analysis limitations", ""]
    lines += [f"- {plain(item)}" for item in report["limitations"]]
    lines += ["", "## Complete batch findings appendix", "",
              "All batch findings remain here even when omitted from the ranked briefing.", ""]
    for index, batch in enumerate(report["batch_findings"], 1):
        lines += [f"### Batch {index}", ""]
        for key in ("discussions", "high_signal_messages", "crypto_intelligence", "actionable_takeaways"):
            for finding in batch[key]:
                lines += [f"**{plain(finding['title'])}** ({key}; minority: {finding['minority_view']})", "",
                          claim(finding["summary"]), ""]
                for row in [*finding["arguments"], *finding["counterarguments"], finding["why_it_matters"]]:
                    lines += [claim(row), ""]
        lines += [f"- {plain(item)}" for item in batch["limitations"]]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save(report: dict, path: Path, *, overwrite: bool = False) -> Path:
    if path.suffix.lower() not in (".md", ".json"):
        raise IntelError("Report output must end in .md or .json.")
    path = path.expanduser().absolute()
    if not path.parent.exists():
        prepare_directory(path.parent)
    if path.is_symlink():
        raise IntelError("Report destination must not be a symbolic link.")
    try:
        # Restrict ACL before writing content. Avoid replacing existing reports.
        with path.open("w" if overwrite else "x", encoding="utf-8") as handle:
            protect(path)
            handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n" if path.suffix.lower() == ".json" else markdown(report))
    except FileExistsError:
        raise IntelError("Output already exists. Choose another filename.") from None
    except OSError:
        raise IntelError("Could not write the report file.") from None
    return path
