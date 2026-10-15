# Telegram GC agent specification

Build a Python 3.11+ personal-account Telegram reader with a CLI, SQLite cache,
raw message exports, optional OpenAI synthesis and seven local MCP tools. Keep the existing member
exporter intact; local research and exports are excluded from the public project.

## Required behavior

Raw extraction is the default. `export` and bare/interactive CLI workflows select
joined groups and locally parsed periods, never need OpenAI credentials/consent,
and never apply AI ranking, summarization or duplicate-content suppression.
Preserve every message ID, author, timestamp, text, URL and source link; include
explicitly labeled immediate reply-parent context. JSON preserves all metadata.
Multiple groups can share one chronological stream or have individual streams.
Split by count/UTF-8 bytes and generate Markdown/JSON indexes with file ranges,
counts, group attribution and integrity hashes. Never clip an oversized message;
flag it as a standalone oversized file. Mark interrupted file writes incomplete.
The former AI loop remains at `interactive --ai`; `ask`/MCP summary stay optional.

1. Explicit local authentication prompts hide phone, login code and 2FA. Persist
   a protected session outside the repository/cloud-sync folder by default.
2. Discover joined groups and subscribed channels; resolve by unique title,
   username, ID or persisted alias. Never join or resolve an unauthorized group.
3. Retrieve every accessible message in a UTC-normalized half-open time window
   `[start, end)`, including all forum topics. No history sample or silent cap.
4. Save IDs, local sender attribution, dates, edits, text, replies, topics,
   forwards, views, reactions, links and media metadata. No media downloads.
5. Retry bounded flood waits/reconnection failures. Preserve partial cache on
   failure but do not mark failed windows complete. Report access limitations.
6. Deduplicate by group/message ID; track completed coverage intervals with a
   freshness TTL. Retrieve missing intervals and new tail; refresh explicitly.
7. Deduplicate repeated content for analysis while retaining original sources;
   extract URLs/tickers/addresses, reply clusters, novelty, evidence, engagement,
   configured expertise, questions, disagreements and sentiment observations.
8. Analyze every distinct message through bounded batches, then hierarchical
   topic consolidation. Retain batch findings and minority/high-value items in
   the JSON report even when the main briefing selects five to ten themes.
9. Reports contain executive summary, ranked discussions, high-signal messages,
   all shared links with context, crypto intelligence and research takeaways.
   Every generated claim cites valid local message references. Claims remain
   attributed opinions/speculation/unverified unless independently established.
10. Local source renderer controls author/time/deep links; reject invented IDs
    and URLs from the model. Treat messages, link text and prior reports as data,
    never instructions. No tool execution or link fetching by the LLM.
11. CLI supports interactive selection, natural questions, exact/rolling time,
    multi-group comparison, follow-ups, Markdown/JSON, cache/session removal.
12. MCP exposes list_telegram_groups, get_telegram_messages,
    summarize_telegram_group, search_telegram_messages, get_telegram_message,
    extract_telegram_links, and export_telegram_messages. Stdio only; no unauthenticated HTTP server.
13. Minimize LLM metadata through pseudonyms and local attribution. Explain that
    text itself can contain personal information and is sent to OpenAI on opt-in.
14. Secrets, sessions, caches, generated reports and analysis checkpoints are
    excluded from Git. Apply restrictive local permissions; never log raw errors
    that could include API credentials or message content.

## Acceptance checks

- Mocked tests cover hidden authentication, read-only request guard, joined-only
  resolution, timezone boundaries, complete pagination, flood resume, permission
  failures, cache reuse/refresh, dedup, forum links, URL extraction and citations.
- Hierarchical analysis tests prove all messages enter batches and invalid source
  references fail closed; checkpointed work resumes without repeating batches.
- MCP protocol smoke test lists seven tools with structured input/output.
- Raw workflows succeed with an absent key, disabled LLM opt-in and an unavailable
  OpenAI SDK. Natural durations, file-size/count splitting, all-message preservation,
  group isolation/combined ordering, reply contexts and index totals are tested.
- Existing exporter tests continue to pass.
- Live integration instructions demonstrate auth once, list, alias, 72-hour
  summary, follow-up and Codex calls. Live checks require the user's local keys
  and authenticated account; automated checks never use real credentials.

## Explicit limits

Telegram may hide pre-join, deleted, restricted or expired history. API exhaustion
means all history returned to this account was read, not proof no messages are
missing. Cached edits/deletions may be stale until TTL/refresh. Media contents
are not transcribed. Ranking is a heuristic; model claims require human review.
Remote ChatGPT integration needs separately authorized hosting/authentication.
