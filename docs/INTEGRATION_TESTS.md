# Live integration checklist

Offline tests never connect to Telegram/OpenAI or read the real `.env`.
These checks use your account locally after you have completed README setup.
Run them yourself; do not paste authentication material into chat.

1. `python -m telegram_intel auth`: enter phone/code/2FA with hidden prompts.
   Run again: no second login should be needed. Check the private session lives
   in the application data folder, outside the repository/OneDrive by default.
2. `python -m telegram_intel groups`: compare names/IDs with your Telegram app.
   DMs and groups you have left must not appear. Select one quiet joined group.
3. `python -m telegram_intel alias testdesk "EXACT GROUP NAME"`.
4. Fetch a small exact range with `messages testdesk --start ... --end ...`.
   Compare first/last timestamps with Telegram. Start is inclusive, end exclusive.
5. Repeat exactly: `cache_only=true`, no history download. Move the end forward:
   only the missing tail is downloaded. `--refresh` reconciles edits/deletions.
6. Test a forum: compare messages from several topics and open their source links.
   Basic legacy chats legitimately have no supported permanent message link.
7. Without an OpenAI key/consent flag, run `export --group testdesk --period
   "seven days" --format both --max-messages 50`. Inspect index.md/index.json.
   Compare window counts with `messages` and Telegram; verify several full-text
   records, numeric sender IDs, timestamps and source links. Check repeated and
   low-engagement posts remain present. Upload one format's parts plus the index.
8. Repeat with two joined groups and `--layout individual`, then `combined`.
   Individual files must isolate groups; combined files must be globally ordered.
   Check all part counts total the window count for each format and all bytes/hashes
   agree with the JSON index. Reply parents outside the window are labeled context
   and excluded from window counts. `--no-reply-context` disables extra requests.
   Optional AI regression: after installing requirements-ai.txt and setting key/
   opt-in, run `ask` and `interactive --ai`, inspect the six report sections and
   use `--follow-up REPORT_ID` to confirm the original analysis still works.
9. Request an empty historical interval and an unknown group ID. Expect an empty
   supported report and a clear authorization/selection error respectively.
10. Close the process during retrieval/analysis. Re-run the exact range/question.
    Partial records stay in SQLite; completed AI batches reuse checkpoints.
    Failed retrieval spans are never represented as completed coverage.
11. Configure/reload Codex per README. Confirm seven tools appear. Ask it to export
    a selected group for the last seven days without summarizing; the primary
    export_telegram_messages tool must return clickable local bundle/index paths
    without OpenAI setup. Retrieve an exact window; continue `next_cursor` to null.
    Search, single-message and links tools should agree with CLI exports.
    Trigger a summary only after explicitly setting up the optional AI feature.
12. Keep the MCP running: it must not open a listening HTTP port. No tool exists
    to send/react/join/delete/read-mark or change account settings.
13. `purge --cache --yes`: clears DB, cached reports/checkpoints and default UUID
    report exports, preserving raw export bundles. `purge --session --yes`: removes local authorization file only.
    Revoke the authorization separately in Telegram Settings if desired.

Do not intentionally create a Telegram flood wait for testing. The offline suite
simulates flood/network/permission failures, including partial retrieval.

Live accuracy checks remain necessary: a valid citation guarantees a retrieved
source exists, not that the model interpreted it correctly or a trade is sound.
