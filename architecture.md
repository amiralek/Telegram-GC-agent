# Architecture

Primary: `CLI/MCP -> service.extract -> joined-dialog gateway -> SQLite ->
raw records + immediate reply contexts -> raw_export -> split files + indexes`.

Optional: `service.summarize -> preprocessing -> OpenAI batch findings ->
hierarchical synthesis -> local source renderer`.

## Modules

- `config.py`, `security.py`: environment settings, protected local storage,
  safe errors, hidden prompts and process lock.
- `models.py`, `time_range.py`: typed Telegram records and timezone windows.
- `store.py`: SQLite messages, joined groups, aliases, coverage intervals,
  analysis checkpoints and report/follow-up state.
- `telegram.py`: guarded Telethon client; local auth is the only context allowing
  authentication requests. All normal MTProto requests must match an explicit
  allowlist; outbound messages, read receipts and account changes are blocked.
- `preprocess.py`: deterministic links, entity detection, content duplicates,
  reply/topic components and bounded explainable ranking.
- `analysis.py`: Responses API structured outputs, pseudonymized evidence,
  token-aware batches, cached findings, hierarchical reduction, source validation.
- `report.py`: local author/date/link attribution, JSON and Markdown exports.
- `raw_export.py`: every original message, deterministic chronological ordering,
  Markdown literal source blocks, full JSON records, byte/count splitting and
  private export bundles with index/hashes. No relevance/content filtering.
- `service.py`: end-to-end retrieval, questions, follow-ups and report persistence.
- `cli.py`, `mcp_server.py`: interactive and structured read-only interfaces.

## Configuration

`configure` saves API credentials in a protected per-user `.env` using hidden
prompts and exclusive creation. CLI/MCP prefer an explicit file, otherwise the
working-directory `.env`, otherwise the per-user file. Existing environment
variables take precedence. No configuration files are merged. Session/cache
paths remain compatible with previous versions. AI credentials are optional.

## Authentication and authorization

Session is `%LOCALAPPDATA%\TelegramIntelligence\account.session` on Windows
(XDG data directory on Unix). A single cross-process lock prevents concurrent
Telethon session use. Windows ACLs restrict data directory/files to current user;
Unix directory/file modes are 700/600. CLI auth supports existing accounts only,
no sign-up, joining, settings changes or logout RPC. `purge --session` deletes
local session only; Telegram Settings can revoke the authorization separately.
Read operations first reload dialogs and select a joined group/channel. Cached
rows are not exposed by MCP after membership authorization fails.

## Cache and completeness

UTC microseconds and `(group_id, message_id)` keys preserve exact boundaries.
Iterate history newest-to-oldest with `limit=None`. Persist each message before
moving the offset; retry from the last saved ID after flood/network failure.
Coverage is saved only after the lower boundary/API exhaustion. Fresh interval
union avoids unnecessary retrieval; expired portions are reconciled and missing
IDs in a successfully refreshed interval are removed. Partial data is retained
with a completeness warning. Recent cache is a snapshot, not a real-time stream.

## Analysis and evidence

Only explicit `ask`, `interactive --ai` or MCP summary operations load the optional
OpenAI SDK. Base dependencies exclude it. Raw period parsing is deterministic and
handles numeric/written hour/day/week durations, with the same UTC boundaries.
Reply contexts use within-window parents, then cached parents; optionally fetch
missing immediate parents from selected authorized groups. Outside-window parents
are labeled context and excluded from window counts. No cross-group fetch occurs
unless that group was explicitly selected. Cached parents may be stale; refresh
revalidates them. Parent access/flood failures never discard child messages.

Every distinct text and deterministic entity/link record enters a token-bounded
batch; oversized text is split with the same source ID. Reply roots and topic IDs
preserve discussion context across batches. Batch findings are checkpointed by
model, question and evidence hash. Hierarchical reductions consolidate topics;
all leaf findings remain in the exported appendix to preserve minority views.
Report source IDs are validated against this request's message set. The model
cannot choose author names, clickable message links or externally fetched facts.
Provider requests have `store=False`, no tools, bounded retries and safe errors.
Names/numeric sender IDs are replaced with request-local participant labels;
message text gets basic phone/email redaction, not a guarantee of anonymization.

## Interfaces

CLI installs as `telegram-intel`, also runnable as `python -m telegram_intel`.
MCP uses SDK v1 `FastMCP`, pinned below v2, stdio; it never prompts for auth.
Message/search results are explicitly paged with a cursor and total count.
History collection and analysis remain exhaustive regardless of response paging.
Tool results label Telegram content as untrusted. Running local stdio does not
publish the data to the internet. Remote transport is intentionally absent;
hosting a connector is a separate opt-in deployment requiring TLS and auth.

`export_telegram_messages` is the primary MCP tool and returns local file paths,
counts, time boundaries and limitations. Telegram access remains read-only, but
the tool correctly advertises local file writes through readOnlyHint=false.
Every export creates a fresh private directory; prior bundles are never overwritten.
Files are chronological per stream; both formats have identical part membership.
Indexes list every file, exact UTF-8 sizes, SHA-256, UTC ranges and per-group counts.
A whole oversized record is explicitly flagged. INCOMPLETE.txt remains on write
failure/interruption. Exports are separate user artifacts and cache purge preserves
them unless the user deletes them directly.
