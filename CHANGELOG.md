# Changelog

## 1.2.0

- Public project title: Telegram GC agent; MIT license and portable documentation.
- Added `configure` with hidden credential prompts, private storage and no overwrite.
- CLI/MCP find a private per-user configuration when no working-directory `.env`
  is present. Explicit `--env-file` and environment variables remain supported.
- Added `telegram-gc-agent` command alias and `--version`; existing entry points remain.
- Added source-package exclusions and Windows/Linux CI for raw and optional AI paths.

## 1.1.0

- Raw Markdown/JSON exports became the default workflow, without OpenAI credentials.
- Added multi-group exports, reply context, automatic splitting and file indexes.
- Added the `export_telegram_messages` MCP tool and natural-language time periods.
- Preserved the original optional AI analysis and local cache/authentication flows.
