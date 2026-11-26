"""Synthetic, in-process spike against the pinned OWUI search handler body.

Run: PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p test_memory_spike.py -v
Requires fastapi, httpx and pydantic, plus OWUI_PINNED_SOURCE pointing to
the pinned backend/open_webui directory. Skips when not configured.
No server, credentials, production databases, network or runtime edits are used.

Only the pinned handler and its request model are compiled from source. FastAPI
routing, validation and dependency injection are real; authentication, permission,
repository, search helper and response model are synthetic. This is not an OWUI
integration test, does not prove OWUI authentication or search semantics, and
does not exercise the manifold or an ACP subprocess. Cancellation covers an
in-process ASGI task, not a real network disconnect or database cancellation.
"""
import ast
import asyncio
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
import httpx
from pydantic import BaseModel


class SyntheticRepository:
    def __init__(self):
        self.rows = {
            'alice': [{'id': 'alice-id', 'content': 'synthetic apple'}],
            'bob': [{'id': 'bob-id', 'content': 'synthetic berry'}],
        }
        self.calls = []
        self.failure = False
        self.started = asyncio.Event()
        self.block = None

    async def get_memories_by_user_id(self, user_id):
        self.calls.append(user_id)
        self.started.set()
        if self.block is not None:
            await self.block.wait()
        if self.failure:
            raise RuntimeError('synthetic repository failure')
        return self.rows.get(user_id, [])


def synthetic_search(rows, *, query, path, memory_id, memory_type, limit):
    # This deliberately simple fake verifies parameter forwarding, not OWUI matching.
    return [row for row in rows
            if (memory_id is None or row['id'] == memory_id)
            and (query is None or query in row['content'])][:limit]


def pinned_handler(repository):
    root = os.environ.get('OWUI_PINNED_SOURCE')
    if not root:
        raise unittest.SkipTest('set OWUI_PINNED_SOURCE to run the pinned-source spike')
    source = Path(root) / 'routers' / 'memories.py'
    data = source.read_bytes()
    expected = '9a1fac03b70bd62975e33febe761ac4ed90ddf98cae32da6dcb5acfa8180d4b0'
    if hashlib.sha256(data).hexdigest() != expected:
        raise AssertionError('memories.py does not match OWUI v0.13.5')
    tree = ast.parse(data, filename=str(source))
    wanted = {'SearchMemoriesForm', 'search_memories'}
    nodes = [node for node in tree.body if getattr(node, 'name', None) in wanted]
    if {node.name for node in nodes} != wanted:
        raise AssertionError('pinned search handler or form is missing')
    handler = next(node for node in nodes if node.name == 'search_memories')
    handler.decorator_list = []  # Register below without importing OWUI side effects.

    async def principal(request: Request):
        identity = request.headers.get('x-synthetic-principal')
        if identity not in ('alice', 'bob'):
            raise HTTPException(status_code=401)
        return SimpleNamespace(id=identity, role='user')

    async def permission(user):
        if user.id == 'bob' and deny_bob[0]:
            raise HTTPException(status_code=403)

    deny_bob = [False]
    namespace = {'BaseModel': BaseModel, 'Literal': Literal, 'Depends': Depends,
                 'get_verified_user': principal, 'check_memories_permission': permission,
                 'Memories': repository, 'search_memory_rows': synthetic_search}
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, str(source), 'exec'), namespace)
    app = FastAPI()
    app.post('/search')(namespace['search_memories'])
    return app, deny_bob


class MemorySpike(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = SyntheticRepository()
        app, self.deny_bob = pinned_handler(self.repo)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                        base_url='http://synthetic.invalid')
        self.addAsyncCleanup(self.client.aclose)

    async def search(self, identity, payload):
        headers = {'x-synthetic-principal': identity} if identity else {}
        return await self.client.post('/search', headers=headers, json=payload)

    async def test_isolation_and_id_binding_across_turns(self):
        first = await self.search('alice', {'query': 'synthetic'})
        self.assertEqual([r['id'] for r in first.json()], ['alice-id'])
        # A previous user's ID and an extra body identity never select that user.
        second = await self.search('bob', {'memory_id': 'alice-id', 'user_id': 'alice'})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json(), [])
        third = await self.search('bob', {'memory_id': 'bob-id'})
        self.assertEqual([r['id'] for r in third.json()], ['bob-id'])
        self.assertEqual(self.repo.calls, ['alice', 'bob', 'bob'])

    async def test_unauthorized_and_denied_do_not_query(self):
        self.assertEqual((await self.search(None, {})).status_code, 401)
        self.deny_bob[0] = True
        self.assertEqual((await self.search('bob', {})).status_code, 403)
        self.assertEqual(self.repo.calls, [])
        self.assertEqual((await self.search('alice', {})).json()[0]['id'], 'alice-id')

    async def test_error_then_retry_as_other_principal(self):
        self.repo.failure = True
        self.assertEqual((await self.search('alice', {})).status_code, 500)
        self.repo.failure = False
        result = await self.search('bob', {})
        self.assertEqual([r['id'] for r in result.json()], ['bob-id'])
        self.assertEqual(self.repo.calls, ['alice', 'bob'])

    async def test_cancel_then_retry_as_other_principal(self):
        self.repo.block = asyncio.Event()
        task = asyncio.create_task(self.search('alice', {}))
        await asyncio.wait_for(self.repo.started.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.repo.block = None
        result = await self.search('bob', {})
        self.assertEqual([r['id'] for r in result.json()], ['bob-id'])
        self.assertEqual(self.repo.calls, ['alice', 'bob'])

    async def test_invalid_form_does_not_query_and_retry_succeeds(self):
        result = await self.search('alice', {'type': 'invalid'})
        self.assertEqual(result.status_code, 422)
        self.assertEqual(self.repo.calls, [])
        self.assertEqual((await self.search('bob', {})).json()[0]['id'], 'bob-id')


if __name__ == '__main__':
    unittest.main()
