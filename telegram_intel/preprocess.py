"""Deterministic evidence preparation; never fetch or execute shared content."""

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import math
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Message


URL_PATTERN = re.compile(r"(?:https?://|www\.)[^\s<>\"\x00-\x1f]+", re.I)
TICKERS = re.compile(r"\$([A-Za-z][A-Za-z0-9]{1,14})\b|\b(BTC|ETH|SOL|USDT|USDC|BNB|XRP|DOGE|AVAX|ARB|OP|HYPE|AAVE|UNI|LINK)\b")
ADDRESSES = re.compile(r"\b0x[a-fA-F0-9]{40}\b|\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
PROTOCOLS = ("Uniswap", "Aave", "Deribit", "Hyperliquid", "Ethena", "Pendle", "Lido",
             "Curve", "Compound", "Jupiter", "Drift", "dYdX", "Aevo", "Synthetix",
             "GMX", "Morpho", "EigenLayer", "Polymarket", "Maker", "Raydium", "Kamino")
STOP = set("the a an to and or of in for is it that this with on at be are was were from as by not you we i have has but all can will do how what when why who which then they our their its your about".split())


def normalize_url(value: str) -> str | None:
    value = value.strip().rstrip(".,;:!?")
    while value.endswith(")") and value.count(")") > value.count("("):
        value = value[:-1]
    value = value.rstrip("]}")
    if value.lower().startswith("www."):
        value = "https://" + value
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            return None
        host = parts.hostname.lower()
        if host in ("twitter.com", "www.twitter.com", "www.x.com"):
            host = "x.com"
        port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid", "dclid")]
        return urlunsplit((parts.scheme.lower(), host + port, parts.path or "/", urlencode(query), parts.fragment))
    except ValueError:
        return None


def extract_urls(text: str, entities=()) -> list[str]:
    candidates = list(URL_PATTERN.findall(text))
    encoded = text.encode("utf-16-le")
    for entity in entities:
        if getattr(entity, "url", None):
            candidates.append(entity.url)
        elif type(entity).__name__ == "MessageEntityUrl":
            start, end = entity.offset * 2, (entity.offset + entity.length) * 2
            candidates.append(encoded[start:end].decode("utf-16-le", errors="replace"))
    return list(dict.fromkeys(url for candidate in candidates if (url := normalize_url(candidate))))


def url_category(url: str) -> str:
    host = urlsplit(url).hostname or ""
    path = urlsplit(url).path.casefold()
    if host in ("x.com", "twitter.com"):
        return "X/Twitter discussions"
    if any(word in host for word in ("tradingview", "dune.com", "defillama", "coinglass", "dexscreener", "nansen", "glassnode", "tokenterminal")):
        return "Trading tools, dashboards, and charts"
    if any(word in host for word in ("arxiv", "substack", "medium.com", "messari", "research")) or "research" in path:
        return "Research articles"
    if host.startswith("docs.") or "/docs" in path or any(name.lower() in host for name in PROTOCOLS):
        return "Protocol websites and documentation"
    return "Other resources"


def shared_links(messages: list[Message]) -> list[dict]:
    result: dict[str, dict] = {}
    for message in messages:
        for url in [*extract_urls(message.text), *message.urls]:
            normalized = normalize_url(url)
            if not normalized:
                continue
            row = result.setdefault(normalized, {"url": normalized, "category": url_category(normalized), "contexts": []})
            if not any(c["source_id"] == message.source_id for c in row["contexts"]):
                row["contexts"].append({"source_id": message.source_id, "text": message.text,
                                        "author": message.sender_name, "timestamp": message.date,
                                        "message_link": message.link})
    return list(result.values())


def entities(text: str) -> dict:
    return {"tickers": sorted({(a or b).upper() for a, b in TICKERS.findall(text)}),
            "addresses": sorted(set(ADDRESSES.findall(text))),
            "protocols": [name for name in PROTOCOLS if re.search(r"\b" + re.escape(name) + r"\b", text, re.I)]}


def content_key(message: Message) -> str:
    text = re.sub(r"\s+", " ", message.text).strip().casefold()
    # Media-only posts, actions and differing URLs must keep separate evidence.
    payload = text + "|" + "|".join(sorted(extract_urls(message.text) + message.urls))
    if not text:
        payload += "|" + message.source_id
    return hashlib.sha256(payload.encode()).hexdigest()


def preprocess(messages: list[Message], expert_ids: frozenset[int] = frozenset()) -> list[dict]:
    ordered = sorted(messages, key=lambda m: (m.date, m.group_id, m.id))
    by_source = {m.source_id: m for m in ordered}
    parent = {m.source_id: m.source_id for m in ordered}

    def root(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(a, b):
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[rb] = ra

    # Exact replies and forum topic lineage take precedence over lexical hints.
    topic_roots, lexical = {}, {}
    words_by_id = {}
    freq = Counter()
    for message in ordered:
        words = {x for x in re.findall(r"[a-z][a-z0-9]{2,}", message.text.lower()) if x not in STOP}
        words_by_id[message.source_id] = words
        freq.update(words)
        reply = f"{message.group_id}:{message.reply_to}"
        if message.reply_to and reply in by_source:
            union(reply, message.source_id)
        if message.topic_id:
            key = (message.group_id, message.topic_id)
            if key in topic_roots:
                union(topic_roots[key], message.source_id)
            else:
                topic_roots[key] = message.source_id
        # Related non-replies are a heuristic, require two shared meaningful words
        # in the same chat within six hours. LLM later names/refines themes.
        votes = Counter()
        for word in words:
            previous = lexical.get((message.group_id, word))
            if previous and (datetime.fromisoformat(message.date) - datetime.fromisoformat(previous.date)).total_seconds() <= 21600:
                votes[previous.source_id] += 1
            lexical[(message.group_id, word)] = message
        for candidate, count in votes.items():
            if count >= 2:
                union(candidate, message.source_id)

    followups = Counter(f"{m.group_id}:{m.reply_to}" for m in ordered if m.reply_to)
    participant_labels = {}
    group_labels = {gid: f"G{index + 1}" for index, gid in enumerate(sorted({m.group_id for m in ordered}))}
    unique = {}
    for message in ordered:
        identity = message.sender_id if message.sender_id is not None else (message.group_id, message.sender_name)
        if identity not in participant_labels:
            participant_labels[identity] = f"P{len(participant_labels) + 1}"
        key = content_key(message)
        occurrence = {"source_id": message.source_id, "group": group_labels[message.group_id],
                      "author": participant_labels[identity], "time": message.date,
                      "reply_source": f"{message.group_id}:{message.reply_to}" if message.reply_to else None,
                      "discussion": root(message.source_id), "topic_id": message.topic_id,
                      "forwarded": bool(message.forwarded)}
        if key in unique:
            row = unique[key]
            row["source_ids"].append(message.source_id)
            row["duplicate_count"] += 1
            row["duplicate_authors"].append(participant_labels[identity])
            row["occurrences"].append(occurrence)
            continue
        detected = entities(message.text)
        words = words_by_id[message.source_id]
        novelty = sum(1 / freq[word] for word in words) / max(1, len(words))
        evidence = min(2, len(message.urls or extract_urls(message.text))) + bool(detected["addresses"])
        actionable = bool(re.search(r"\b(invalidat\w*|stop.loss|target|entry|risk|yield|airdrop|farm\w*|liquidity|hedge|funding|research)\b", message.text, re.I))
        disagreement = bool(re.search(r"\b(disagree|however|but|incorrect|counter|risk|wrong|bearish|bullish)\b", message.text, re.I))
        announcement = bool(re.search(r"\b(launch\w*|announc\w*|upgrade|exploit|hack|listing|proposal)\b", message.text, re.I))
        reactions = sum(max(0, int(x.get("count", 0))) for x in message.reactions)
        engagement = min(2, math.log1p(followups[message.source_id] + reactions) / 2)
        expertise = int(message.sender_id in expert_ids)
        score = round(2 * novelty + 2 * evidence + actionable + disagreement + announcement + engagement + expertise, 3)
        unique[key] = {"source_ids": [message.source_id], "duplicate_count": 0,
                       "occurrences": [occurrence],
                       "duplicate_authors": [], "group": group_labels[message.group_id],
                       "author": participant_labels[identity], "time": message.date,
                       "text": message.text, "reply_source": f"{message.group_id}:{message.reply_to}" if message.reply_to else None,
                       "discussion": root(message.source_id), "topic_id": message.topic_id,
                       "forwarded": bool(message.forwarded), "media_type": (message.media or {}).get("type"),
                       "urls": message.urls or extract_urls(message.text), "entities": detected,
                       "rank": score, "ranking_factors": {"novelty": round(novelty, 3), "evidence_presence": evidence,
                       "actionable_language": actionable, "disagreement_language": disagreement,
                       "announcement_language": announcement, "engagement": round(engagement, 3),
                       "user_configured_expertise": expertise},
                       "question": "?" in message.text,
                       "sentiment_hint": "mixed" if re.search(r"\bbullish\b", message.text, re.I) and re.search(r"\bbearish\b", message.text, re.I)
                       else "bullish" if re.search(r"\bbullish\b", message.text, re.I)
                       else "bearish" if re.search(r"\bbearish\b", message.text, re.I) else "unknown"}
    return list(unique.values())
