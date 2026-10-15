# Validation record

Validated 2026-10-15 on Windows using Python 3.12.14.

- `python -m unittest discover -s tests -v`: **123 tests passed**, including the
  prior 83 regressions, 28 raw-export tests and 12 first-run configuration tests.
- `python -m pip check`: no broken requirements.
- `python -m compileall -q telegram_intel`: passed.
- CLI `--help` worked when launched from the parent directory after editable install.
- MCP stdio subprocess initialized and listed seven tools with structured schemas.
- Raw CLI/MCP exports succeeded with an empty OpenAI key and disabled opt-in.
- A subprocess blocked OpenAI SDK imports and still exported MD/JSON, constructed
  CLI/MCP schemas and confirmed the analysis module was never loaded.
- Tests checked count/UTF-8 splitting, all source text, repeated/zero-engagement
  messages, combined/individual grouping, reply context, index sizes/hashes,
  partial history and incomplete-write markers.
- Windows private-directory ACL and account-lock tests passed.
- First-run configuration uses hidden prompts, refuses overwrites and supports
  per-user credentials fallback; CLI version/help need no credentials.
- Wheel and source distribution built successfully; inventories exclude private
  data, credentials, sessions, caches, exports and research files.
- Release source allowlist and personal-path/credential-pattern scan passed.
- `.env.example` contains credential placeholders; real `.env` is Git-ignored.
- Original member-exporter regression suite: 14 tests passed, included in the 83.

Tested main dependencies: Telethon 1.45.0, OpenAI SDK 2.54.0, MCP SDK 1.30.0.
Base requirements exclude OpenAI; requirements-ai.txt and the [ai] package extra
retain the optional analysis engine. The raw-only test file uses base fixtures
and needs no OpenAI SDK. The local environment snapshot is excluded from the
public project because it contains machine-specific paths.

The tests use fabricated in-memory messages and mocked Telegram/OpenAI responses.
No real credentials are test fixtures, and no real Telegram or OpenAI calls were
made. A local MCP protocol exchange is real but makes no account requests.
The Windows sandbox prevented temporary-file cleanup in initial runs; successful
offline test runs used the normal host permissions. No test failures remain.

Live personal-account login, the selected groups' visibility, source-link opening,
model access, actual API cost and semantic briefing quality await the user's local
setup. Follow `INTEGRATION_TESTS.md`; valid source IDs do not guarantee correct
interpretation of those messages.

GitHub Actions is configured for Windows and Ubuntu with Python 3.11-3.13,
including a base-only raw workflow before installing the optional AI extra.
Those remote jobs have not been run as part of this local validation record.
