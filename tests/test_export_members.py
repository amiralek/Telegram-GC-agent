import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telethon import errors, types

import export_members as exporter


def user(user_id, **fields):
    return SimpleNamespace(id=user_id, username=fields.get('username'),
                           first_name=fields.get('first_name'), last_name=fields.get('last_name'))


class FakeClient:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = 0

    def iter_participants(self, entity, limit):
        self.calls += 1
        assert limit is None
        async def iterate():
            for item in next(self.pages):
                if isinstance(item, Exception):
                    raise item
                yield item
        return iterate()


class ExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_bio_returns_extended_profile_about(self):
        client = AsyncMock(return_value=SimpleNamespace(full_user=SimpleNamespace(about='Hello,\nworld')))
        bio, failed = await exporter.fetch_bio(client, types.User(id=1), exporter.FloodBudget(10))
        self.assertEqual(bio, 'Hello,\nworld')
        self.assertFalse(failed)

    async def test_denied_bio_is_blank(self):
        client = AsyncMock(side_effect=errors.UserIdInvalidError(None))
        bio, failed = await exporter.fetch_bio(client, types.User(id=1), exporter.FloodBudget(10))
        self.assertEqual(bio, '')
        self.assertTrue(failed)

    async def test_bio_export_retains_ids_for_unavailable_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'members.csv'
            client = FakeClient([[user(1), user(2)]])
            with patch.object(exporter, 'fetch_bio', new_callable=AsyncMock,
                              side_effect=[('Hello,\nworld', False), ('', True)]), \
                    patch.object(exporter.asyncio, 'sleep', new_callable=AsyncMock):
                result = await exporter.export_participants(client, object(), output,
                                                           exporter.FloodBudget(10), 2, False, True)
            with output.open(encoding='utf-8-sig', newline='') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row['user_id'] for row in rows], ['1', '2'])
            self.assertEqual(rows[0]['bio'], 'Hello,\nworld')
            self.assertEqual(rows[1]['bio'], '')
            self.assertEqual(result, 2)

    async def export(self, pages, count=None, restricted=False, budget=None):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'members.csv'
            client = FakeClient(pages)
            result = await exporter.export_participants(
                client, object(), output, budget or exporter.FloodBudget(10), count, restricted
            )
            with output.open(encoding='utf-8-sig', newline='') as handle:
                rows = list(csv.DictReader(handle))
            return result, rows, client.calls

    async def test_deduplication_numeric_ids_and_unicode_csv(self):
        result, rows, calls = await self.export([[user(1234567890123, first_name='Name,\nසිංහල'),
                                                 user(1234567890123), user(7)]], count=2)
        self.assertEqual(result, 0)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['user_id'], '1234567890123')
        self.assertEqual(rows[0]['first_name'], 'Name,\nසිංහල')
        self.assertEqual(rows[1]['username'], '')

    async def test_flood_wait_restart_deduplicates_without_losing_rows(self):
        with patch.object(exporter.asyncio, 'sleep', new_callable=AsyncMock) as sleep:
            result, rows, calls = await self.export(
                [[user(1), errors.FloodWaitError(None, capture=2)], [user(1), user(2)]], count=2
            )
        sleep.assert_awaited_once_with(2)
        self.assertEqual(calls, 2)
        self.assertEqual([r['user_id'] for r in rows], ['1', '2'])
        self.assertEqual(result, 0)

    async def test_permission_failure_preserves_partial_csv(self):
        result, rows, calls = await self.export([[user(1), errors.ChatAdminRequiredError(None)]], count=10)
        self.assertEqual(result, 2)
        self.assertEqual(len(rows), 1)

    async def test_silent_subset_is_flagged(self):
        result, rows, calls = await self.export([[user(1)]], count=10)
        self.assertEqual(result, 2)

    async def test_hidden_members_flagged_even_with_equal_count(self):
        result, rows, calls = await self.export([[user(1)]], count=1, restricted=True)
        self.assertEqual(result, 2)

    async def test_excessive_flood_wait_preserves_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'members.csv'
            client = FakeClient([[user(1), errors.FloodWaitError(None, capture=11)]])
            with self.assertRaises(exporter.ExportError):
                await exporter.export_participants(client, object(), output, exporter.FloodBudget(10), 2, False)
            self.assertIn('1,,,', output.read_text(encoding='utf-8-sig'))

    async def test_unjoined_invite_does_not_join(self):
        client = AsyncMock(return_value=types.ChatInvite(title='Private', photo=types.PhotoEmpty(1),
                                                       participants_count=1, color=0))
        with self.assertRaisesRegex(exporter.ExportError, 'has not joined'):
            await exporter.resolve_group(client, 'https://t.me/+ExampleInvite')
        self.assertEqual(client.await_count, 1)

    async def test_numeric_id_resolved_from_dialogs(self):
        chat = types.Chat(id=42, title='Group', photo=types.ChatPhotoEmpty(), participants_count=1,
                          date=None, version=1)
        async def dialogs():
            yield SimpleNamespace(entity=types.User(id=42))
            yield SimpleNamespace(entity=chat)
        client = SimpleNamespace(iter_dialogs=dialogs)
        self.assertIs(await exporter.resolve_group(client, '-42'), chat)

    async def test_invalid_code_then_two_step_authentication(self):
        client = SimpleNamespace(
            connect=AsyncMock(), is_user_authorized=AsyncMock(return_value=False),
            send_code_request=AsyncMock(return_value=SimpleNamespace(phone_code_hash='test-hash')),
            sign_in=AsyncMock(side_effect=[errors.PhoneCodeInvalidError(None),
                                           errors.SessionPasswordNeededError(None), None]),
            get_me=AsyncMock(return_value=SimpleNamespace(bot=False)),
        )
        with patch.dict(exporter.os.environ, {'TELEGRAM_PHONE': '+123456789'}), \
                patch.object(exporter, 'hidden_input', side_effect=['wrong', 'valid', 'password']):
            await exporter.authenticate(client, exporter.FloodBudget(10))
        self.assertEqual(client.sign_in.await_count, 3)
        client.sign_in.assert_awaited_with(password='password')

    async def test_bot_account_rejected(self):
        client = SimpleNamespace(connect=AsyncMock(), is_user_authorized=AsyncMock(return_value=True),
                                 get_me=AsyncMock(return_value=SimpleNamespace(bot=True)))
        with self.assertRaisesRegex(exporter.ExportError, 'personal Telegram account'):
            await exporter.authenticate(client, exporter.FloodBudget(10))

    async def test_existing_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'members.csv'
            output.write_text('existing', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                await exporter.export_participants(FakeClient([[user(1)]]), object(), output,
                                                   exporter.FloodBudget(10), 1, False)
            self.assertEqual(output.read_text(encoding='utf-8'), 'existing')


if __name__ == '__main__':
    unittest.main()
