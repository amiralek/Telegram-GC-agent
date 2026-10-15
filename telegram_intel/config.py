from dataclasses import dataclass, field
import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from .security import IntelError, hidden_input, prepare_data_directory, prepare_directory, protect


def default_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData/Local") / "TelegramIntelligence"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local/share") / "telegram-intelligence"


def credentials_path(env_file: str | Path | None = None) -> Path:
    if env_file is not None:
        return Path(env_file).expanduser().absolute()
    local = Path.cwd() / ".env"
    if local.exists() or local.is_symlink():
        return local
    return default_data_dir() / ".env"


def configure(env_file: str | Path | None = None, *, timezone: str = "UTC") -> Path:
    """Create a private configuration locally; never echo credentials or overwrite."""
    path = credentials_path(env_file)
    if path.exists() or path.is_symlink():
        raise IntelError(f"Configuration already exists at {path}. Edit it locally; no changes were made.")
    try:
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise IntelError("Choose a valid IANA timezone, such as UTC or Asia/Colombo.") from None
    api_id = hidden_input("Telegram API ID (hidden): ").strip()
    api_hash = hidden_input("Telegram API hash (hidden): ").strip()
    if (not api_id.isascii() or not api_id.isdecimal() or int(api_id) <= 0
            or len(api_hash) != 32 or any(c not in "0123456789abcdefABCDEF" for c in api_hash)):
        raise IntelError("Invalid Telegram API ID/hash. Use your personal app credentials from my.telegram.org/apps.")
    if path.parent == default_data_dir():
        prepare_data_directory(path.parent)
    elif not path.parent.exists():
        prepare_directory(path.parent)
    try:
        with path.open("x", encoding="utf-8") as handle:
            protect(path)
            handle.write(f"TELEGRAM_API_ID={api_id}\nTELEGRAM_API_HASH={api_hash}\nTELEGRAM_INTEL_TIMEZONE={timezone}\n")
    except FileExistsError:
        raise IntelError("Configuration already exists; no credentials were overwritten.") from None
    return path


@dataclass
class Config:
    api_id: int
    api_hash: str = field(repr=False)
    data_dir: Path
    openai_key: str = field(default="", repr=False)
    model: str = "gpt-4.1-mini"
    timezone: str = "Asia/Colombo"
    allow_llm: bool = False
    cache_ttl: int = 300
    max_flood_wait: int = 300
    batch_tokens: int = 6000
    expert_ids: frozenset[int] = frozenset()
    analysis_config_error: bool = False

    @property
    def session_path(self) -> Path:
        return self.data_dir / "account.session"

    @classmethod
    def load(cls, env_file: str | Path | None = None, *, require_telegram: bool = True) -> "Config":
        env_path = credentials_path(env_file)
        if env_path.is_symlink():
            raise IntelError("Credentials file must not be a symbolic link.")
        if env_path.exists():
            protect(env_path)
        load_dotenv(env_path, override=False, encoding="utf-8-sig")
        try:
            api_id = int(os.environ.get("TELEGRAM_API_ID", "")) if require_telegram else 0
            api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
            if require_telegram and (api_id <= 0 or len(api_hash) != 32 or any(c not in "0123456789abcdefABCDEF" for c in api_hash)):
                raise ValueError
            default_dir = default_data_dir()
            timezone = os.environ.get("TELEGRAM_INTEL_TIMEZONE", "Asia/Colombo") if require_telegram else "Asia/Colombo"
            ZoneInfo(timezone)
            analysis_config_error = False
            batch_tokens, expert_ids = 6000, frozenset()
            if require_telegram:
                try:
                    batch_tokens = int(os.environ.get("TELEGRAM_INTEL_BATCH_TOKENS", "6000"))
                    expert_ids = frozenset(int(x.strip()) for x in os.environ.get("TELEGRAM_INTEL_EXPERT_IDS", "").split(",") if x.strip())
                    analysis_config_error = not 1500 <= batch_tokens <= 24000
                except ValueError:
                    analysis_config_error = True
            config = cls(api_id=api_id, api_hash=api_hash,
                         data_dir=Path(os.environ.get("TELEGRAM_INTEL_DATA_DIR", str(default_dir))).expanduser().resolve(),
                         openai_key=os.environ.get("OPENAI_API_KEY", ""),
                         model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"), timezone=timezone,
                         allow_llm=os.environ.get("TELEGRAM_INTEL_ALLOW_LLM", "false").lower() == "true",
                         cache_ttl=int(os.environ.get("TELEGRAM_INTEL_CACHE_TTL_SECONDS", "300")) if require_telegram else 300,
                         max_flood_wait=int(os.environ.get("TELEGRAM_INTEL_MAX_FLOOD_WAIT", "300")) if require_telegram else 300,
                         batch_tokens=batch_tokens, expert_ids=expert_ids,
                         analysis_config_error=analysis_config_error)
            if config.cache_ttl < 0 or config.max_flood_wait < 0:
                raise ValueError
            return config
        except (ValueError, KeyError, ZoneInfoNotFoundError):
            raise IntelError("Invalid configuration. Run 'python -m telegram_intel configure' or set TELEGRAM_API_ID/HASH and check timezone/numeric settings in .env.") from None

    def require_llm(self) -> None:
        if not self.allow_llm:
            raise IntelError("AI analysis sends selected message text to OpenAI. Set TELEGRAM_INTEL_ALLOW_LLM=true to opt in.")
        if not self.openai_key or self.openai_key == "your_openai_api_key":
            raise IntelError("Set OPENAI_API_KEY locally before requesting AI analysis.")
        if self.analysis_config_error:
            raise IntelError("Fix optional AI settings: batch tokens must be 1500-24000 and expert IDs must be numeric.")
