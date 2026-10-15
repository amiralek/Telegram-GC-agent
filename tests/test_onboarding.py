"""Offline first-run and portable configuration tests; fabricated credentials only."""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from telegram_intel import __version__
from telegram_intel.cli import main, parser, run
from telegram_intel.config import Config, configure, credentials_path
from telegram_intel.security import IntelError


class OnboardingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name).absolute()
        self.cwd = self.root / "project"
        self.cwd.mkdir()
        self.app = self.root / "app"
        self.env_patch = patch.dict(os.environ, {"HOME": str(self.root), "USERPROFILE": str(self.root)}, clear=True)
        self.env_patch.start()
        self.cwd_patch = patch("telegram_intel.config.Path.cwd", return_value=self.cwd)
        self.cwd_patch.start()
        self.app_patch = patch("telegram_intel.config.default_data_dir", return_value=self.app)
        self.app_patch.start()
        self.prompts = patch("telegram_intel.config.hidden_input", side_effect=["123456", "a" * 32])

    def tearDown(self):
        self.app_patch.stop()
        self.cwd_patch.stop()
        self.env_patch.stop()
        self.temp.cleanup()

    def test_default_configuration_is_private_user_file(self):
        self.assertEqual(credentials_path(), self.app / ".env")

    def test_working_directory_configuration_has_precedence(self):
        (self.cwd / ".env").touch()
        self.assertEqual(credentials_path(), self.cwd / ".env")

    def test_explicit_missing_file_never_falls_back_to_other_credentials(self):
        (self.cwd / ".env").write_text("TELEGRAM_API_ID=123\nTELEGRAM_API_HASH=" + "a" * 32)
        with self.assertRaises(IntelError):
            Config.load(self.root / "missing.env")

    def test_configure_creates_valid_private_credentials_without_openai(self):
        with self.prompts:
            path = configure(timezone="UTC")
        config = Config.load()
        self.assertEqual(path, self.app / ".env")
        self.assertEqual(config.api_id, 123456)
        self.assertEqual(config.api_hash, "a" * 32)
        self.assertEqual(config.timezone, "UTC")
        self.assertEqual(config.data_dir, self.app)
        self.assertFalse(config.allow_llm)
        self.assertFalse(config.openai_key)
        self.assertNotIn(config.api_hash, repr(config))

    def test_existing_file_not_overwritten_or_prompted(self):
        path = self.cwd / ".env"
        path.write_text("preserve me")
        with patch("telegram_intel.config.hidden_input") as prompt, self.assertRaises(IntelError):
            configure()
        prompt.assert_not_called()
        self.assertEqual(path.read_text(), "preserve me")

    def test_environment_values_override_saved_file(self):
        with self.prompts:
            configure()
        with patch.dict(os.environ, {"TELEGRAM_API_ID": "789", "TELEGRAM_API_HASH": "b" * 32}):
            config = Config.load()
        self.assertEqual(config.api_id, 789)
        self.assertEqual(config.api_hash, "b" * 32)

    def test_invalid_credentials_never_written_or_in_error(self):
        secret = "invalid-secret-do-not-display"
        with patch("telegram_intel.config.hidden_input", side_effect=["123", secret]):
            with self.assertRaises(IntelError) as raised:
                configure()
        self.assertNotIn(secret, str(raised.exception))
        self.assertFalse((self.app / ".env").exists())

    def test_invalid_timezone_stops_before_asking_for_secrets(self):
        with patch("telegram_intel.config.hidden_input") as prompt, self.assertRaises(IntelError):
            configure(timezone="Not/A_Real_Zone")
        prompt.assert_not_called()

    def test_permissions_failure_prevents_secret_write(self):
        path = self.cwd / "custom.env"
        with self.prompts, patch("telegram_intel.config.protect", side_effect=IntelError("permission error")):
            with self.assertRaises(IntelError):
                configure(path)
        self.assertEqual(path.read_bytes(), b"")

    async def test_configure_cli_does_not_connect_or_load_configuration_first(self):
        output = io.StringIO()
        with self.prompts, redirect_stdout(output), patch("telegram_intel.cli.open_service", side_effect=AssertionError("network access")):
            await run(parser().parse_args(["configure"]))
        self.assertIn("Next run", output.getvalue())
        self.assertNotIn("a" * 32, output.getvalue())
        self.assertNotIn("123456", output.getvalue())

    def test_version_cli_needs_no_credentials(self):
        output = io.StringIO()
        with patch("sys.argv", ["telegram-gc-agent", "--version"]), redirect_stdout(output):
            with self.assertRaises(SystemExit) as stopped:
                main()
        self.assertEqual(stopped.exception.code, 0)
        self.assertIn(__version__, output.getvalue())

    def test_missing_configuration_message_explains_first_step(self):
        with self.assertRaisesRegex(IntelError, "configure"):
            Config.load()
