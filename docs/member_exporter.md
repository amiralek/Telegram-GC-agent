# Telegram group member export

Exports permanent numeric Telegram user IDs with username, first name, and last name to `members.csv`. Uses a personal account through Telethon's MTProto client; bot accounts are rejected. Missing profile fields become empty cells. IDs remain numeric, and rows are deduplicated by `user_id`.

## Windows setup (PowerShell)

Install Python 3.11 or newer, then open PowerShell in this directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
notepad .env
```

Get your own `api_id` and `api_hash` from [Telegram API development tools](https://my.telegram.org/apps), and replace the placeholders in `.env`. Existing environment variables take precedence over `.env`. `TELEGRAM_PHONE` is optional; use an international phone number when setting it. Never add login codes or two-step verification passwords to `.env`.

## Run

```powershell
.\.venv\Scripts\python.exe .\export_members.py "@your_group"
```

To include accessible member bios:

```powershell
.\.venv\Scripts\python.exe .\export_members.py "@your_group" --include-bio
```

This adds a `bio` column using [Telegram's extended user info API](https://core.telegram.org/method/users.getFullUser). Bio lookup makes one extra request per unique member, spaced by 0.5 seconds, and respects the same server rate limits. It can take much longer. Missing or inaccessible bios are blank; failed profile lookups are counted in the console and yield exit code `2`. IDs and usernames are retained even when a profile lookup fails. Only bios Telegram returns to your account are included.

Other accepted targets (replace these examples):

```powershell
.\.venv\Scripts\python.exe .\export_members.py "https://t.me/your_group"
.\.venv\Scripts\python.exe .\export_members.py "https://t.me/+your_invite_hash"
.\.venv\Scripts\python.exe .\export_members.py "https://t.me/joinchat/your_invite_hash"
.\.venv\Scripts\python.exe .\export_members.py -1001234567890
```

Numeric IDs are resolved from this account's dialogs to obtain the required access hash. Prefer marked IDs: `-100...` for supergroups and negative chat IDs for basic groups. Positive raw IDs also work when unambiguous. This script never joins groups automatically: join private groups in Telegram first, including approval when required. A revoked or expired invite can fail even if you are a member; use the group ID or a valid link instead.

Enter your phone number, login code, and optional two-step verification password in the hidden terminal prompts. Run in an interactive terminal: the script refuses to fall back to an echoed login prompt. It stores the authentication session only in memory, never creates a session file, and requires login again on each run. Disconnecting discards the local session; you can also revoke the authorization in Telegram's Settings → Devices.

The CSV is UTF-8 with a BOM for Windows/Excel compatibility, with this header:

```csv
user_id,username,first_name,last_name
```

An existing output file is never overwritten. Move it aside or use `--output members_second.csv`. The script flushes rows as they arrive and retains a partial CSV on permission errors, network errors, rate-limit exhaustion, or Ctrl+C. Failure before enumeration starts creates no CSV.

## Rate limits and visibility

[`iter_participants()`](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.chats.ChatMethods.iter_participants) paginates automatically with no local member limit. On `FloodWaitError`, the script waits the server-requested duration and restarts enumeration, deduplicating previously saved users. It permits at most five waits per run and up to 3,600 seconds per wait. Use `--max-flood-wait 300` to stop if Telegram requests a wait longer than five minutes; `0` stops immediately on a rate limit.

Regular members and admins can export whatever Telegram permits their account to enumerate. Telegram may hide members, require admin permissions, cap enumeration, or silently return a subset. The script reports extracted and reported counts, flags known hidden participants or count shortfalls, and preserves only users returned through normal participant enumeration. It performs no search splitting, message scraping, account rotation, or privacy bypass. Equal counts do not guarantee a snapshot: membership can change while paging; without a reported count completeness cannot be verified.

Exit codes: `0` = enumeration finished without a detected limitation; `2` = partial export or detected visibility/count limitation; `1` = error; `130` = interruption. Inspect the console message and CSV, since Telegram can impose silent limits.

Keep `.env` and exported member data private. `.gitignore` excludes credentials, session files, and CSVs. Profile text is exported verbatim; if opening it in a spreadsheet, import profile columns as text so member-supplied text is not interpreted as formulas.

## Offline checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

These checks mock Telegram; they do not log in or confirm live access to a particular group.
