import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import manifold


class ManifoldTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.log = Path(directory.name) / 'acp.jsonl'
        self.pipe = manifold.Pipe()
        self.pipe.valves.AGY_EXECUTABLE = str(Path(__file__).with_name('fake_acp.py').resolve())
        self.pipe.valves.ACTUAL_MODEL = 'model-b'
        self.body = {'model': 'agy.gemini-4-hydrogen', 'stream': True,
                     'messages': [{'role': 'user', 'content': 'test'}]}

    def records(self):
        if not self.log.exists():
            return []
        with self.log.open() as stream:
            return [json.loads(line) for line in stream if line.endswith('\n')]

    def fake(self, scenario):
        return patch.object(manifold, '_child_env', return_value={
            'PATH': os.environ['PATH'], 'FAKE_ACP_SCENARIO': scenario,
            'FAKE_ACP_LOG': str(self.log),
        })

    async def collect(self, scenario):
        async def consume():
            response = await self.pipe.pipe(self.body)
            return [frame async for frame in response.body_iterator]
        with self.fake(scenario):
            frames = await asyncio.wait_for(consume(), 5)
        self.assert_reaped()
        return frames

    def assert_reaped(self):
        pid = next(r['pid'] for r in self.records() if r.get('event') == 'started')
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    async def test_stream(self):
        frames = await self.collect('stream')
        chunks = [json.loads(frame.removeprefix('data: '))['choices'][0] for frame in frames[:-1]]
        self.assertEqual([chunk['delta'].get('content') for chunk in chunks], ['hello ', 'world', None])
        self.assertEqual(chunks[-1]['finish_reason'], 'stop')
        self.assertEqual(frames[-1], 'data: [DONE]\n\n')
        self.assertIn('model-b', [r.get('params', {}).get('modelId') for r in self.records()])

    async def test_diagnostics_opt_in_and_sanitized(self):
        self.assertFalse(self.pipe.valves.DEBUG_ACP_EVENTS)
        with patch.object(manifold._LOG, 'warning') as log:
            await self.collect('diagnostics')
            log.assert_not_called()
        self.pipe.valves.DEBUG_ACP_EVENTS = True
        with self.assertLogs('owui_agy_acp', level='WARNING') as captured:
            await self.collect('diagnostics')
        output = str(captured.output)
        self.assertIn('update=tool_call_update status=failed', output)
        self.assertNotIn('secret-marker', output)

    async def test_diagnostic_permission(self):
        self.pipe.valves.DEBUG_ACP_EVENTS = True
        with self.assertLogs('owui_agy_acp', level='WARNING') as captured:
            await self.collect('permission')
        self.assertIn('permission requested', str(captured.output))
        self.assertNotIn('unsafe', str(captured.output))

    async def test_agy_log_file_opt_in(self):
        self.assertFalse(self.pipe.valves.DEBUG_AGY_LOG_FILE)
        log_dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(log_dir, ignore_errors=True))
        self.pipe.valves.DEBUG_ACP_EVENTS = True
        self.pipe.valves.DEBUG_AGY_LOG_FILE = True
        self.pipe.valves.AGY_LOG_DIRECTORY = str(log_dir)
        await self.collect('stream')
        records = self.records()
        args = next(r['argv'] for r in records if r.get('event') == 'started')
        self.assertEqual(args[:2], ['acp', '--sandbox'])
        self.assertIn('--log-file', args)
        path = Path(args[args.index('--log-file') + 1])
        self.assertEqual(path.parent, log_dir)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.stat().st_size, 0)

    async def test_model_error_never_prompts(self):
        frames = await self.collect('model_error')
        self.assertIn('did not accept', frames[0])
        self.assertNotIn('session/prompt', [r.get('method') for r in self.records()])

    async def test_reject_permission(self):
        await self.collect('permission')
        replies = [r['result'] for r in self.records() if r.get('id') == 991 and 'result' in r]
        self.assertEqual(replies, [{'outcome': {'outcome': 'selected', 'optionId': 'reject'}}])

    async def test_timeout_reaps(self):
        with patch.object(manifold, '_IDLE_TIMEOUT', 0.2):
            frames = await self.collect('timeout')
        self.assertIn('timed out', frames[0])

    async def test_cancel_and_reap(self):
        with self.fake('timeout'):
            response = await self.pipe.pipe(self.body)
            task = asyncio.create_task(anext(response.body_iterator))
            try:
                async with asyncio.timeout(3):
                    while not any(r.get('method') == 'session/prompt' for r in self.records()):
                        await asyncio.sleep(0.02)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assert_reaped()
