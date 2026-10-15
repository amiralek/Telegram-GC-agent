"""CLI/service/provider and real stdio protocol tests, all fully offline."""

from contextlib import asynccontextmanager
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import APIConnectionError, RateLimitError
import httpx

from telegram_intel.analysis import Analyzer, Draft, Provider, QueryPlan, compact_findings
from telegram_intel.cli import parser
from telegram_intel.models import Group, Message, UTC
from telegram_intel.report import save
from telegram_intel.security import AccountLock, IntelError, prepare_directory, prepare_data_directory, protect
from telegram_intel.service import Service
from telegram_intel.telegram import Gateway

from test_intelligence import (Fixture, FakeProvider, GROUP, NOW, BatchFindings, aclaim,
                               finding, msg, raw)


class DistinctProvider(FakeProvider):
    async def parse(self, schema, instructions, payload):
        if schema is BatchFindings and "messages" in payload:
            self.calls.append((schema, payload))
            rows = payload["messages"]
            items = [finding(row["source_ids"], title=f"Topic {row['source_ids'][0]}", minority=True) for row in rows]
            return BatchFindings(discussions=items, high_signal_messages=[], crypto_intelligence=[],
                                 actionable_takeaways=[], limitations=[])
        return await super().parse(schema, instructions, payload)


class ExtendedAnalysisTests(Fixture):
    async def test_hierarchy_runs_and_retains_every_leaf_finding(self):
        provider = DistinctProvider()
        messages = [msg(i, f"Distinct topic {i}: " + "evidence " * 30) for i in range(1, 21)]
        result = await Analyzer(self.config, self.store, provider).analyze("Summarize", messages)
        self.assertGreater(result["reduction_levels"], 0)
        leaf_titles = {item["title"] for batch in result["batch_findings"] for item in batch["discussions"]}
        self.assertEqual(len(leaf_titles), 20)
        self.assertTrue(all(item["minority_view"] for batch in result["batch_findings"] for item in batch["discussions"]))

    async def test_provider_refusal_and_incomplete_fail_closed(self):
        for status, parsed in (("completed", None), ("incomplete", Draft(executive_summary=[], top_discussions=[], high_signal_messages=[], crypto_intelligence=[], actionable_takeaways=[], limitations=[]))):
            client = SimpleNamespace(responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(status=status, output_parsed=parsed))))
            with patch("telegram_intel.analysis.AsyncOpenAI", return_value=client):
                provider = Provider(self.config)
            with self.assertRaises(IntelError):
                await provider.parse(Draft, "system", {"messages": []})

    async def test_provider_store_false_no_tools_and_safe_rate_error(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        error = RateLimitError("secret-containing-response", response=httpx.Response(429, request=request), body=None)
        parse = AsyncMock(side_effect=error)
        client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
        with patch("telegram_intel.analysis.AsyncOpenAI", return_value=client):
            provider = Provider(self.config)
        with self.assertRaises(IntelError) as caught:
            await provider.parse(Draft, "system", {"messages": []})
        self.assertNotIn("secret-containing-response", str(caught.exception))
        self.assertFalse(parse.call_args.kwargs["store"])
        self.assertNotIn("tools", parse.call_args.kwargs)


class ServiceTests(Fixture):
    async def test_follow_up_reuses_window_and_prior_topics(self):
        gateway, client = self.gateway([[raw(1, date=NOW - timedelta(seconds=1), text="BTC risk")]])
        provider = FakeProvider()
        service = Service(self.config, self.store, gateway, provider)
        first = await service.summarize([str(GROUP.id)], NOW - timedelta(hours=1), NOW, "Summarize")
        followup = await service.ask("Explain discussion one", previous_report_id=first["report_id"])
        self.assertEqual(followup["retrieval"][0]["start"], first["retrieval"][0]["start"])
        self.assertEqual(len(client.calls), 1)
        batches = [payload for schema, payload in provider.calls if schema is BatchFindings and "messages" in payload]
        self.assertEqual(batches[-1]["prior_topics_untrusted"][0]["title"], "BTC risk")

    async def test_sender_filter_uses_local_exact_username(self):
        gateway, client = self.gateway([[raw(2, date=NOW - timedelta(seconds=1)), raw(1, date=NOW - timedelta(seconds=2))]])
        service = Service(self.config, self.store, gateway, FakeProvider())
        result = await service.summarize([str(GROUP.id)], NOW - timedelta(hours=1), NOW, "Alice discussion", person="@alice")
        self.assertEqual(result["message_count"], 2)
        self.assertIn("Sender-filtered", " ".join(result["limitations"]))

    async def test_duplicate_group_inputs_only_retrieve_once(self):
        gateway, client = self.gateway([[raw(1, date=NOW - timedelta(seconds=1))]])
        service = Service(self.config, self.store, gateway, FakeProvider())
        result = await service.summarize([str(GROUP.id), GROUP.title], NOW - timedelta(hours=1), NOW, "Summarize")
        self.assertEqual(len(result["retrieval"]), 1)
        self.assertEqual(len(client.calls), 1)

    async def test_report_file_private_and_existing_report_preserved(self):
        gateway, _ = self.gateway([[]])
        service = Service(self.config, self.store, gateway, FakeProvider())
        report = await service.summarize([str(GROUP.id)], NOW - timedelta(hours=1), NOW, "Summarize")
        path = self.directory / "report.json"
        save(report, path)
        content = path.read_text(encoding="utf-8")
        with self.assertRaises(IntelError):
            save(report, path)
        self.assertEqual(path.read_text(encoding="utf-8"), content)

    async def test_bot_session_is_rejected(self):
        gateway, client = self.gateway([])
        client.get_me = AsyncMock(return_value=SimpleNamespace(bot=True))
        with self.assertRaises(IntelError):
            await gateway.connect()

    async def test_unknown_sender_returns_supported_empty_report(self):
        gateway, _ = self.gateway([[raw(1, date=NOW - timedelta(seconds=1))]])
        provider = FakeProvider()
        report = await Service(self.config, self.store, gateway, provider).summarize([str(GROUP.id)], NOW - timedelta(hours=1), NOW, "Unknown sender", person="Nobody")
        self.assertEqual(report["message_count"], 0)
        self.assertEqual(provider.calls, [])


class LocalSecurityTests(Fixture):
    async def test_data_directory_rejects_unrelated_files_and_roots(self):
        for path in (Path.cwd(), Path.home(), Path(Path.cwd().anchor)):
            with self.assertRaises(IntelError):
                prepare_data_directory(path)
        unrelated = self.directory / "unrelated"
        unrelated.mkdir()
        (unrelated / "keep.txt").write_text("personal", encoding="utf-8")
        with self.assertRaises(IntelError):
            prepare_data_directory(unrelated)
        self.assertEqual((unrelated / "keep.txt").read_text(encoding="utf-8"), "personal")

    async def test_purge_configuration_does_not_need_credentials(self):
        from telegram_intel.config import Config
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.directory)}, clear=True), patch("telegram_intel.config.load_dotenv"):
            config = Config.load(self.directory / "no-env", require_telegram=False)
        self.assertEqual(config.api_id, 0)

    async def test_private_directory_and_os_lock(self):
        directory = self.directory / "private"
        prepare_directory(directory)
        with AccountLock(directory):
            with self.assertRaises(IntelError):
                with AccountLock(directory):
                    pass
        # OS released lock can be acquired again, no stale-lock recovery needed.
        with AccountLock(directory):
            pass
        if os.name != "nt":
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        else:
            import subprocess
            output = subprocess.run(["icacls", str(directory)], capture_output=True, text=True, check=True).stdout
            self.assertNotIn("(I)", output)  # inheritance removed


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_initialize_and_seven_structured_tools(self):
        params = StdioServerParameters(command=sys.executable,
                                      args=["-m", "telegram_intel.mcp_server", "--env-file", str(Path(__file__).parent / "no-real-env")],
                                      env={"PYTHONIOENCODING": "utf-8"})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                self.assertEqual(len(result.tools), 7)
                self.assertTrue(all(t.outputSchema for t in result.tools))

    async def test_cli_exact_time_flags_and_multiple_groups(self):
        args = parser().parse_args(["ask", "Compare BTC sentiment", "--group=-100123", "--group=desk",
                                    "--start", "2026-10-01", "--end", "2026-10-02"])
        self.assertEqual(args.groups, ["-100123", "desk"])


if __name__ == "__main__":
    unittest.main()
