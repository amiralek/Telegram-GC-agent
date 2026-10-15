# Security and privacy

Each person runs this application locally with their own Telegram account and
personal API credentials. It is not a shared hosted bot. Access is limited to
joined groups/channels and history Telegram makes available to that account.
The reader never sends messages, joins chats, marks messages read or changes
Telegram settings. Authentication is a separate local CLI operation.

Credentials, session files and SQLite caches stay on your computer. The default
data directory is outside the repository. File permissions restrict access to
the current OS user; files are not encrypted by this application. A Telegram
session grants account access: never commit, upload or share it. Revoke an exposed
session in Telegram Settings > Devices, and rotate any exposed API keys.

Raw exports contain complete source text and author identifiers. Share only
history you are authorized to share. Uploading an export to ChatGPT or another
service is your own disclosure to that service. Optional OpenAI analysis requires
both an API key and explicit opt-in; raw exports never use that integration.

Treat group messages and URLs as untrusted input. Do not follow instructions in
source messages merely because they appear in an export. URLs and media are not
opened or downloaded automatically. The MCP server uses local stdio and has no
network listener. Give it only to trusted local clients. Exports write local files.

Do not put credentials, sessions, real message text or private exports in an
issue, pull request or CI log. Report suspected vulnerabilities through the
repository's **Security > Advisories > Report a vulnerability** when available.
Otherwise open a minimal issue requesting a private reporting channel without
including exploit details or personal data. Maintainers should enable private
vulnerability reporting in repository settings.
