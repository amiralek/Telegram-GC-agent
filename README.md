# Telegram GC agent

Export all accessible messages from your joined Telegram groups into chronological
Markdown/JSON files, then upload the files to ChatGPT or let Codex analyze them.
**No OpenAI key, LLM consent flag or OpenAI SDK is needed for this workflow.**
Telethon personal-account authentication, SQLite caching and local MCP remain.
The original AI briefing engine is available only when explicitly requested.

## Install on Windows (PowerShell)

Install **Python 3.11 or newer** and Git, then run:

```powershell
git clone https://github.com/amiralek/Telegram-GC-agent.git
cd Telegram-GC-agent
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m telegram_intel configure
.\.venv\Scripts\python.exe -m telegram_intel auth
.\.venv\Scripts\python.exe -m telegram_intel groups
```

Get your personal API ID and hash at
[my.telegram.org/apps](https://my.telegram.org/apps), following
[Telegram's application setup](https://core.telegram.org/api/obtaining_api_id).
Select **Desktop** when creating your application. The `configure` command asks
for these credentials with hidden input and saves them in private local app data.
The separate `auth` command prompts for your phone, Telegram login code and optional
2FA password, also hidden. Enter secrets only in your own terminal. Each person
uses their own Telegram account and credentials; this is a local tool, not a
shared Telegram bot. No bot token is required.

Export a group (replace the placeholder with a title or ID shown by `groups`):

```powershell
.\.venv\Scripts\python.exe -m telegram_intel export --group "ACTUAL GROUP NAME" --period "seven days" --format both --output-dir .\exports
```

For a menu, run `python -m telegram_intel interactive` using the same virtual
environment. Select group numbers, a period and an export format. The installed
`telegram-gc-agent` and existing `telegram-intel` commands are aliases for
`python -m telegram_intel`; activate the virtual environment to use them directly.
Activation is optional when using the explicit Python path above.

## macOS / Linux

```sh
git clone https://github.com/amiralek/Telegram-GC-agent.git
cd Telegram-GC-agent
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m telegram_intel configure
.venv/bin/python -m telegram_intel auth
.venv/bin/python -m telegram_intel groups
.venv/bin/python -m telegram_intel export --group "ACTUAL GROUP NAME" --period 72h --format both
```

Use `.venv/bin/python` in place of the Windows executable in later examples.
GitHub Actions is configured to test Windows and Linux; local validation is on
Windows. No live Telegram account or paid AI service is used in CI.

## Configuration and existing installations

Configuration precedence is: existing process environment variables, then the
explicit global `--env-file` argument; without that argument, a working-directory
`.env` takes precedence over the private per-user `.env`. These files are never
merged. `configure` refuses to overwrite an existing configuration. Use
`.env.example` as a reference for optional settings; never publish your real file.
For a custom file, put the flag **before** the subcommand:

```powershell
.\.venv\Scripts\python.exe -m telegram_intel --env-file "C:\path\to\private.env" configure --timezone Asia/Colombo
.\.venv\Scripts\python.exe -m telegram_intel --env-file "C:\path\to\private.env" auth
```

New configurations use **UTC**. Change `TELEGRAM_INTEL_TIMEZONE` to an IANA timezone
such as `Europe/London` or `Asia/Colombo`. Older configurations retain their
existing behavior; configurations without that setting default to `Asia/Colombo`
for compatibility. Phone/login codes/2FA passwords are never saved in `.env`.

Session/cache and the default credentials file live in
`%LOCALAPPDATA%\TelegramIntelligence` on Windows, or
`${XDG_DATA_HOME:-~/.local/share}/telegram-intelligence` on Unix. They stay outside
the repository. File permissions restrict them to the current OS user; they are
not encrypted. `TELEGRAM_INTEL_DATA_DIR` can move the session/cache to a dedicated
folder; it does not change the default credentials lookup location. Avoid
cloud-synced folders for credentials and sessions. Only one CLI/MCP process may
use an account at a time.

Existing users can keep their `.env`, `.intel-venv`, session and cache. Run
`.\.intel-venv\Scripts\python.exe -m pip install .` to update, then use that
interpreter in place of `.venv` below. You do not need to run `configure` again.
The program never joins groups, sends messages, marks history read or changes
Telegram settings. Use a unique joined-group title, `@username`, numeric ID or
local alias. Duplicate titles require IDs. The message reader does not accept
invite links; join in Telegram first and choose the group from `groups`.

## Troubleshooting

- **Authenticate locally first:** run `python -m telegram_intel auth` with the
  same interpreter and `--env-file` as your export/MCP process. Login cannot happen
  inside an MCP request. Existing sessions are reused until revoked or expired.
- **Invalid configuration:** run `configure` for a new installation, or edit your
  existing private file. Environment variables override file values.
- **Group not found / permission error:** check `groups`, use the numeric ID for
  ambiguous names, and verify that your account can view that history in Telegram.
- **Rate limit / partial export:** the app respects bounded flood waits. Check
  the index warnings and retry later with `--refresh`; never assume missing
  history is absent from Telegram.
- **Account busy:** close or disconnect the other CLI/MCP process first.
- **Hidden input unavailable:** use an interactive local terminal. Login does not
  fall back to echoed input or accept credentials in command arguments.

## Periods and group selection

Periods are parsed locally without an LLM. Supported examples:

- `24h`, `48h`, `72h`, `7d`, `2w`
- `seven days`, `last 48 hours`, `past twenty-four hours`
- `over the last three days`, `seventy two hours`, `a week`
- `yesterday`, `today`, `this week` (Monday to now)

Default period is `72h`. Date/time inputs use your configured timezone unless an
explicit ISO offset or `Z` is supplied. Set `TELEGRAM_INTEL_TIMEZONE` to change it. Start is
inclusive and end exclusive. Unsupported phrases fail clearly rather than being
guessed. Exact dates and `--period` cannot be combined:

```powershell
.\.venv\Scripts\python.exe -m telegram_intel alias desk "ACTUAL GROUP NAME"
.\.venv\Scripts\python.exe -m telegram_intel export --group desk --period 48h
.\.venv\Scripts\python.exe -m telegram_intel export --group desk --start "2026-10-01" --end "2026-10-04" --format json
```

## Multiple groups, splitting and upload files

```powershell
# One global chronological stream, both file formats
.\.venv\Scripts\python.exe -m telegram_intel export --group desk --group "OTHER GROUP NAME" --period 72h --layout combined --format both --output-dir .\exports

# Separate chronological streams for each group
.\.venv\Scripts\python.exe -m telegram_intel export --group desk --group "OTHER GROUP NAME" --period "seven days" --layout individual --format md --output-dir .\exports

# Smaller files for easier manual analysis
.\.venv\Scripts\python.exe -m telegram_intel export --group desk --period 72h --max-messages 200 --max-bytes 500000 --format both
```

Each command creates a new private bundle under the chosen parent directory.
Without `--output-dir`, the parent is the private app data folder's `exports`
directory. Previous files are never overwritten. Example combined bundle:

```text
telegram-export-YYYYMMDDTHHMMSSZ-uniqueid/
  index.md
  index.json
  messages-part-000001.md
  messages-part-000001.json
  messages-part-000002.md
  messages-part-000002.json
```

Default splitting targets **1,000 messages or 2 MiB of UTF-8 per data file**,
whichever occurs first. Both formats use the same part membership. Individual
layout names files by group ID and restarts part numbers per group. Combined
layout orders all groups together by UTC timestamp, group ID, then message ID.
The index describes every file's group counts, message count and UTC boundaries;
JSON also records byte sizes and SHA-256 integrity hashes.

A single message with context larger than the byte target is kept intact in a
standalone file and flagged as oversized; no text is clipped. Interrupted disk
writes leave `INCOMPLETE.txt`; retry to make a new bundle using the cached history.
A completed file bundle can still contain **PARTIAL HISTORY** if Telegram blocked
or interrupted retrieval; indexes/data headers disclose this explicitly.

Upload `index.md` and all **Markdown parts**, or the JSON parts plus an index.
Choose one format to avoid counting messages twice. The index includes guidance
for an analyst to examine all files, retain minority/low-engagement views and cite
source IDs/time/Telegram links. Uploading files sends their raw contents to the
client/provider you choose; this application makes no OpenAI request during export.

## What raw exports preserve

Every retrieved message is present, including repeated text, empty/media-only
posts, service actions and zero-engagement messages. Only repeated occurrences
of the same numeric group/message ID are deduplicated. No AI preprocessing,
ranking, summarization or sender filter is applied to raw exports.

Markdown includes group title/ID, numeric message/source ID, author name/username/
ID, local and UTC timestamp, verbatim message text, shared URLs, original Telegram
link, replies/topics, views/reactions, edits, forward/media metadata. Source text
is in literal blocks and explicitly labeled untrusted so it cannot become active
Markdown instructions. JSON preserves the full record fields and original text.

Immediate reply parents are copied as labeled context: first use a window message,
then cache, then request a missing parent from the same explicitly selected group.
Outside-window parents are **not** counted as window messages. Cross-group parents
are fetched only when that other group was explicitly selected. No recursive reply
chain is downloaded. Missing/restricted parents are marked unavailable and never
cause child messages to be omitted. Additional parent requests stop after a rate,
access or network error. Use `--no-reply-context` to disable extra outside-window
requests; in-window context and all reply IDs remain.

No shared URL is opened and no media file is downloaded/transcribed. Private links
need an authorized Telegram account; legacy basic chats have no supported permanent
message link. Cached parents may be stale until `--refresh`. Raw files contain
voluntarily posted personal/profile data without the optional AI pipeline's
redaction; protect them as you would the original group history.

## Caching and existing commands

History retrieval still uses `iter_messages(limit=None)` and exact UTC boundaries.
Fresh completed SQLite intervals are reused (300-second default TTL); new tail
intervals are fetched incrementally. TTL expiry and `--refresh` reconcile edits and
deletions. Flood waits/reconnections remain bounded; partial messages are retained
and missing history is disclosed. API exhaustion cannot prove deleted/hidden/pre-
join messages do not exist. No privacy or access restrictions are bypassed.

The original direct JSON retrieval and link commands remain available:

```powershell
.\.venv\Scripts\python.exe -m telegram_intel messages desk --period "seven days" --output history.json
.\.venv\Scripts\python.exe -m telegram_intel links desk --period yesterday --output links.json
```

Use `export` for richer raw Markdown/JSON bundles, reply context, multiple groups,
automatic splitting and indexes. Existing `auth`, `groups`, `alias`, `ask`, `purge`
and the member exporter remain; see [member exporter instructions](docs/member_exporter.md).
Cache/session removal commands are unchanged:

```powershell
.\.venv\Scripts\python.exe -m telegram_intel purge --cache --yes
.\.venv\Scripts\python.exe -m telegram_intel purge --session --yes
```

Raw export bundles are separate artifacts and are **preserved by cache purge**.
Delete selected bundles yourself when no longer needed. Session deletion is local;
revoke the authorization separately in Telegram Settings if desired.

## Codex / MCP workflow

Authenticate once with the CLI, install the package, then configure your MCP
client to launch the virtual environment Python as a local stdio server. The
per-user credentials file works from any working directory. For Codex, run this
from the cloned project folder:

```powershell
$telegramPython = (Resolve-Path .\.venv\Scripts\python.exe).Path
codex mcp add telegram-intel -- $telegramPython -m telegram_intel.mcp_server
codex mcp list
```

The [Codex MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) explains
stdio setup. Existing clients can use the same executable/argument array. No keys
or authentication codes belong in client command arguments. Long exports may need
a longer client tool timeout. Only one CLI/MCP request may use the account at once.

If your client times out on a busy group, adjust the existing Codex entry through
its settings rather than adding a second server. For example:

```toml
[mcp_servers.telegram-intel]
command = 'C:\path\to\Telegram-GC-agent\.venv\Scripts\python.exe'
args = ['-m', 'telegram_intel.mcp_server']
startup_timeout_sec = 30
tool_timeout_sec = 900
```

Tell your Codex agent:

> Export all accessible messages from ACTUAL GROUP NAME for the last seven days
> into Markdown and JSON files. Include reply context, split large exports and
> give me clickable links to the index and data files. Do not summarize them.

The primary tool is `export_telegram_messages`, for example:

```json
{
  "groups": ["desk"],
  "period": "seven days",
  "format": "both",
  "layout": "combined",
  "max_messages": 1000,
  "max_bytes": 2097152
}
```

Optional tool inputs include `output_dir`, `refresh`, `include_reply_context`, and
exact `start_datetime`/`end_datetime` instead of `period`. It returns `ok`, index
paths, data-file paths, counts, time ranges, group attribution, split settings,
integrity hashes and retrieval/context warnings. It does not return the entire
message corpus into the agent's context unless you request separate retrieval.
Telegram access is read-only, but this tool correctly advertises local file writes
(`readOnlyHint=false`) because it saves files. It never overwrites prior bundles.

| Tool | Purpose | OpenAI required? |
| --- | --- | --- |
| `export_telegram_messages` | Primary: save complete raw file bundles and indexes | No |
| `list_telegram_groups` | Joined-group catalog and aliases | No |
| `get_telegram_messages` | Complete accessible window, explicitly paged response | No |
| `search_telegram_messages` | Literal search of accessible window, paged response | No |
| `get_telegram_message` | Single source record or found=false | No |
| `extract_telegram_links` | Deduplicated shared links with context, paged response | No |
| `summarize_telegram_group` | Optional original AI briefing | Yes |

Raw retrieval/search/link tools accept either exact dates or a natural `period`.
For paged results, use the first response's exact `metadata.start/end` on subsequent
pages instead of recalculating a rolling period. Follow `next_cursor` to null;
refresh only the first page. Existing exact-date callers remain compatible.

MCP stays local stdio and exposes no public HTTP server. A local server is not
automatically available in ordinary ChatGPT; uploading the exported files requires
no custom connector. Remote MCP hosting/tunneling remains a separate explicit
opt-in deployment with authentication and account/workspace permissions. See the
[official connection guidance](https://developers.openai.com/plugins/deploy/connect-chatgpt)
if you separately want that integration.

## Optional original OpenAI analysis

Raw extraction does not need this installation or configuration. To use `ask`,
`interactive --ai` or the MCP summary tool, install the optional dependency:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
# Alternative: .\.venv\Scripts\python.exe -m pip install -e ".[ai]"
```

Then add locally to `.env`:

```ini
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4.1-mini
TELEGRAM_INTEL_ALLOW_LLM=true
```

```powershell
.\.venv\Scripts\python.exe -m telegram_intel ask "What mattered, including risks and disagreements?" --group desk --period 72h --output briefing.md
.\.venv\Scripts\python.exe -m telegram_intel interactive --ai
```

The original evidence-backed sections, batching/checkpoints, JSON/Markdown reports,
sender selection, cross-group comparison and `--follow-up REPORT_ID` are retained.
Only this explicit analysis path sends selected text to OpenAI, with pseudonymous
participants and basic email/phone redaction. It uses `store=False`; consult
[OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data) for
provider retention. Valid source references do not guarantee semantic accuracy.

## Tests and project structure

Raw-only offline tests need just the base dependencies:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_raw_exports.py -v
```

For all original and new tests, install `requirements-ai.txt` for the optional AI
regression tests, then run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

Tests cover raw completeness/repeated posts, natural periods, exact date boundaries,
message/count/UTF-8 splitting, group attribution/order, indexes/hashes, reply context,
partial history/write failures, CLI/MCP operation without keys/consent and a subprocess
where the OpenAI SDK is unavailable. Original auth/cache/analysis/exporter tests remain.
The suite covers Windows storage permissions and a real local MCP protocol
exchange. See the validation record for the latest local results.
Live account verification still requires your local Telegram login; no real account
or paid provider requests are made by automated tests. See
[live integration checklist](docs/INTEGRATION_TESTS.md) and [validation record](docs/VALIDATION.md).

```text
telegram_intel/raw_export.py   all-message Markdown/JSON bundles, splitting/indexes
telegram_intel/service.py      raw retrieval/reply context; optional analysis
telegram_intel/time_range.py   deterministic local periods and UTC boundaries
telegram_intel/cli.py          export-first CLI / interactive --ai opt-in
telegram_intel/mcp_server.py   seven structured tools, local stdio
telegram_intel/telegram.py     guarded Telethon personal-account reader
telegram_intel/store.py        unchanged incremental SQLite cache
requirements.txt              base dependencies, no OpenAI SDK
requirements-ai.txt            optional AI dependencies
pyproject.toml                editable install; optional [ai] extra
.env.example                  Telegram setup; OpenAI entries commented out
spec.md / architecture.md     updated requirements and design
export_members.py             original member exporter preserved
```

## License and contributions

MIT licensed; see [LICENSE](LICENSE). Contributions and offline development
instructions are in [CONTRIBUTING.md](CONTRIBUTING.md). Read [SECURITY.md](SECURITY.md)
before sharing exports or reporting an issue. Private sessions, credentials,
research spreadsheets and group exports are excluded from the public project.
