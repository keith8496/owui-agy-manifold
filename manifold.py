"""
title: Antigravity ACP
version: 0.1.0
description: Experimental single-turn text streaming over an ACP subprocess.
"""

import asyncio
import json
import logging
import os
import re
import signal
import tempfile
import threading
import time
import uuid
from contextlib import suppress

from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse


_LOG = logging.getLogger("owui_agy_acp")

_BASE_ID = "gemini-4-hydrogen"
_SLOTS = threading.BoundedSemaphore(2)  # Per loaded module in each OWUI worker.
_MAX_FRAME = 256 * 1024
_MAX_PROMPT_CHARS = 32 * 1024
_RPC_TIMEOUT = 30
_TURN_TIMEOUT = 120
_IDLE_TIMEOUT = 30
_CLEANUP_GRACE = 0.5


class _Failure(Exception):
    """Only fixed, safe-to-display messages may be passed to this exception."""


def _child_env():
    # Do not pass API keys, DB credentials, OWUI tokens, or loader overrides.
    keys = ("PATH", "HOME", "LANG", "LC_ALL", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
            "XDG_DATA_HOME", "XDG_STATE_HOME")
    env = {key: os.environ[key] for key in keys if key in os.environ}
    return {**env, "NO_COLOR": "1", "TERM": "dumb"}


class _ACP:
    def __init__(self, proc, debug=False):
        self.proc = proc
        self.debug = debug
        self.session = None
        self.seq = 0
        self.prompt_pending = False

    async def send(self, message):
        data = json.dumps({"jsonrpc": "2.0", **message}, separators=(",", ":"))
        self.proc.stdin.write(data.encode("ascii") + b"\n")
        await self.proc.stdin.drain()

    async def read(self):
        try:
            line = await self.proc.stdout.readline()
        except ValueError:
            raise _Failure("ACP returned an oversized frame.") from None
        if not line:
            raise _Failure("ACP exited before completing the request.")
        if not line.endswith(b"\n"):
            raise _Failure("ACP returned an incomplete frame.")
        try:
            msg = json.loads(line)
        except (ValueError, RecursionError):
            raise _Failure("ACP returned an invalid JSON frame.") from None
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            raise _Failure("ACP returned an invalid frame.")
        return msg

    async def start(self, method, params):
        self.seq += 1
        await self.send({"id": self.seq, "method": method, "params": params})
        return self.seq

    async def receive(self, request_id):
        """Return a response or a same-session notification, handling client requests inline."""
        while True:
            msg = await self.read()
            if "method" not in msg:
                if type(msg.get("id")) is not int or msg["id"] != request_id:
                    raise _Failure("ACP returned an unexpected response ID.")
                if "error" in msg or not isinstance(msg.get("result"), dict):
                    raise _Failure("ACP rejected the request or returned an invalid result.")
                return True, msg["result"]

            method, rpc_id = msg["method"], msg.get("id")
            if not isinstance(method, str):
                raise _Failure("ACP returned an invalid method.")
            if "id" in msg:
                if type(rpc_id) not in (str, int) and rpc_id is not None:
                    raise _Failure("ACP returned an invalid request ID.")
                if method == "session/request_permission":
                    if self.debug:
                        _LOG.warning("ACP diagnostic: permission requested; rejecting")
                    params = msg.get("params")
                    options = params.get("options") if isinstance(params, dict) else None
                    reject = next((item["optionId"] for item in options
                                   if isinstance(item, dict) and item.get("kind") == "reject_once"
                                   and isinstance(item.get("optionId"), str) and item["optionId"]), None
                                  ) if isinstance(options, list) else None
                    if reject is None:
                        raise _Failure("ACP requested permission without a reject-once option.")
                    await self.send({"id": rpc_id, "result": {"outcome": {
                        "outcome": "selected", "optionId": reject,
                    }}})
                else:
                    await self.send({"id": rpc_id, "error": {"code": -32601,
                                                             "message": "Method not supported"}})
                continue
            if method == "session/update" and self.session is not None:
                params = msg.get("params")
                if isinstance(params, dict) and params.get("sessionId") == self.session:
                    update = params.get("update")
                    if isinstance(update, dict):
                        if self.debug:
                            kind = update.get("sessionUpdate")
                            status = update.get("status")
                            safe_kinds = ("tool_call", "tool_call_update", "agent_message_chunk",
                                          "agent_thought_chunk", "plan")
                            safe_status = ("pending", "in_progress", "completed", "failed")
                            if kind != "agent_message_chunk":
                                _LOG.warning("ACP diagnostic: update=%s status=%s",
                                             kind if kind in safe_kinds else "other",
                                             status if status in safe_status else "none")
                        return False, update

    async def rpc(self, method, params):
        async with asyncio.timeout(_RPC_TIMEOUT):
            request_id = await self.start(method, params)
            while True:
                done, payload = await self.receive(request_id)
                if done:
                    return payload

    async def setup(self, cwd, model):
        init = await self.rpc("initialize", {
            "protocolVersion": 1,
            "clientInfo": {"name": "owui-agy-manifold", "version": "0.1.0"},
            "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False},
                                   "terminal": False},
        })
        if type(init.get("protocolVersion")) is not int or init["protocolVersion"] != 1:
            raise _Failure("AGY does not support ACP protocol version 1.")
        new = await self.rpc("session/new", {"cwd": cwd, "mcpServers": []})
        self.session = new.get("sessionId")
        if not isinstance(self.session, str) or not self.session:
            raise _Failure("ACP did not create a session.")
        # This POC targets the AGY bridge's native set_model request, not a fallback.
        models = new.get("models")
        if models is not None:
            available = models.get("availableModels") if isinstance(models, dict) else None
            if not isinstance(available, list) or not any(
                isinstance(entry, dict) and entry.get("modelId") == model for entry in available
            ):
                raise _Failure("The configured model is not advertised by AGY.")
        try:
            selected = await self.rpc("session/set_model", {"sessionId": self.session, "modelId": model})
        except _Failure:
            raise _Failure("AGY did not accept the configured model.") from None
        if any(selected.get(key, model) != model for key in ("currentModelId", "modelId")):
            raise _Failure("AGY did not confirm the configured model.")

    async def prompt(self, text, emit):
        self.prompt_pending = True
        request_id = await self.start("session/prompt", {
            "sessionId": self.session, "prompt": [{"type": "text", "text": text}],
        })
        emitted = False
        while True:
            async with asyncio.timeout(_IDLE_TIMEOUT):
                done, payload = await self.receive(request_id)
            if done:
                self.prompt_pending = False
                reason = payload.get("stopReason")
                if reason not in ("end_turn", "max_tokens", "max_turn_requests"):
                    raise _Failure("ACP stopped without completing the text response.")
                if not emitted:
                    raise _Failure("ACP returned no text.")
                return "stop" if reason == "end_turn" else "length"
            if payload.get("sessionUpdate") != "agent_message_chunk":
                continue
            content = payload.get("content")
            if not isinstance(content, dict) or content.get("type") != "text":
                raise _Failure("ACP returned unsupported non-text content.")
            part = content.get("text")
            if not isinstance(part, str):
                raise _Failure("ACP returned an invalid text chunk.")
            if part:
                await emit(part)
                emitted = True


async def _dispose(proc, acp):
    if acp is not None and acp.prompt_pending and proc.returncode is None:
        with suppress(Exception):
            async with asyncio.timeout(_CLEANUP_GRACE):
                await acp.send({"method": "session/cancel", "params": {"sessionId": acp.session}})
    proc.stdin.close()
    # Reap the child and terminate descendants in its process group, even if
    # the leader has already exited. Drain stdout without retaining its contents.
    with suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGTERM)

    async def reap():
        while await proc.stdout.read(65536):
            pass
        await proc.wait()

    try:
        async with asyncio.timeout(_CLEANUP_GRACE):
            await reap()
    except TimeoutError:
        pass
    finally:
        with suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
    try:
        async with asyncio.timeout(_CLEANUP_GRACE):
            await reap()
    except TimeoutError:
        # A descendant outside the group may have inherited stdout. There is
        # no public close API for asyncio Process's stdout pipe transport.
        transport = proc._transport.get_pipe_transport(1)
        if transport is not None:
            transport.close()


async def _run_turn(executable, model, text, emit, debug=False,
                    debug_log_file=False, log_directory=""):
    if not _SLOTS.acquire(blocking=False):
        return None, "ACP is busy; retry shortly."
    workdir = spawn = proc = acp = None
    error = finish = None
    try:
        async with asyncio.timeout(_TURN_TIMEOUT):
            workdir = tempfile.TemporaryDirectory(prefix="owui-agy-")
            agy_log = None
            if debug and debug_log_file:
                if not os.path.isabs(log_directory) or not os.path.isdir(log_directory):
                    raise _Failure("Configure an existing absolute private directory for AGY debug logs.")
                fd, agy_log = tempfile.mkstemp(prefix="agy-acp-", suffix=".log", dir=log_directory)
                os.close(fd)
                _LOG.warning("ACP diagnostic: AGY log file created at %s; it may contain sensitive data", agy_log)
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                executable, "acp", "--sandbox", *(
                    ["--log-file", agy_log] if agy_log else []
                ), cwd=workdir.name, env=_child_env(),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, start_new_session=True, limit=_MAX_FRAME,
            ))
            # Canceling during spawn must not orphan a child before we know its PID.
            proc = await asyncio.shield(spawn)
            acp = _ACP(proc, debug)
            await acp.setup(workdir.name, model)
            finish = await acp.prompt(text, emit)
    except _Failure as exc:
        error = str(exc)
    except TimeoutError:
        error = "ACP timed out."
    except Exception:
        error = "ACP could not start or the connection failed."
    finally:
        async def cleanup():
            try:
                child = proc
                if child is None and spawn is not None:
                    with suppress(Exception):
                        child = await spawn
                if child is not None:
                    await _dispose(child, acp)
            finally:
                try:
                    if workdir is not None:
                        workdir.cleanup()
                finally:
                    _SLOTS.release()

        cleanup_task = asyncio.create_task(cleanup())
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            # Cleanup owns the slot until it finishes even on repeated cancellation.
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.shield(cleanup_task)
            raise
        except Exception:
            finish, error = None, "ACP cleanup failed."
    return finish, error


def _sse(data):
    return "data: " + json.dumps(data, separators=(",", ":")) + "\n\n"


async def _stream(executable, model, public_model, text, debug=False,
                  debug_log_file=False, log_directory=""):
    # The producer's deadline still runs if a slow or abandoned consumer is
    # suspended at a yield. Keep its queue bounded independently of the pipes.
    chunks = asyncio.Queue(maxsize=8)
    ready = asyncio.Event()

    async def emit(part):
        await chunks.put(part)
        ready.set()

    worker = asyncio.create_task(_run_turn(executable, model, text, emit, debug, debug_log_file,
                                                log_directory))
    worker.add_done_callback(lambda _: ready.set())
    identity = {"id": "chatcmpl-" + uuid.uuid4().hex, "created": int(time.time()),
                "object": "chat.completion.chunk", "model": public_model}

    def frame(delta, finish=None):
        return _sse({**identity, "choices": [{"index": 0, "delta": delta,
                                             "finish_reason": finish}]})

    try:
        first = True
        while True:
            while not chunks.empty():
                part = chunks.get_nowait()
                delta = {"content": part}
                if first:
                    delta["role"] = "assistant"
                    first = False
                yield frame(delta)
            if worker.done():
                break
            ready.clear()
            await ready.wait()
        finish, error = worker.result()
        if error:
            yield _sse({"error": {"detail": error}})
        else:
            yield frame({}, finish)
            yield "data: [DONE]\n\n"
    finally:
        if not worker.done():
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker


def _prompt_text(body):
    messages = body.get("messages")
    # No role flattening or silent history loss: only one user turn is supported.
    if not isinstance(messages, list) or len(messages) != 1:
        raise _Failure("ACP POC supports one user message; history and system prompts are unsupported.")
    message = messages[0]
    if (not isinstance(message, dict) or message.get("role") != "user"
            or set(message) - {"role", "content"}):
        raise _Failure("ACP POC supports only a plain user message.")
    text = message.get("content")
    if not isinstance(text, str) or not text.strip() or len(text) > _MAX_PROMPT_CHARS:
        raise _Failure("ACP POC requires nonempty plain text of at most 32768 characters.")
    return text


class Pipe:
    class Valves(BaseModel):
        AGY_EXECUTABLE: str = Field(default="agy", description="Executable name on PATH or absolute path.")
        ACTUAL_MODEL: str = Field(default="gemini-4-hydrogen-medium", description="Exact AGY model ID.")
        DEBUG_ACP_EVENTS: bool = Field(default=False, description="Log sanitized ACP tool and permission event types/statuses; test environments only.")
        DEBUG_AGY_LOG_FILE: bool = Field(default=False, description="Write an AGY ACP log in AGY_LOG_DIRECTORY. Logs may contain sensitive data; disposable tests only.")
        AGY_LOG_DIRECTORY: str = Field(default="", description="Existing private absolute directory for opt-in AGY logs; manage retention and deletion manually.")

    def __init__(self):
        self.type = "manifold"
        self.valves = self.Valves()

    def pipes(self):
        return [{"id": _BASE_ID, "name": "Gemini 4 Hydrogen (ACP POC)"}]

    async def pipe(self, body: dict, __tools__=None, __files__=None):
        public_model = body.get("model")
        model, executable = self.valves.ACTUAL_MODEL, self.valves.AGY_EXECUTABLE
        if not isinstance(public_model, str) or public_model.rpartition(".")[2] != _BASE_ID:
            raise _Failure("Unknown ACP manifold model.")
        if body.get("stream") is not True:
            raise _Failure("ACP POC only supports streaming requests.")
        if __tools__ or __files__ or any(body.get(key) for key in (
            "tools", "tool_choice", "functions", "function_call", "files", "attachments",
        )):
            raise _Failure("ACP POC does not support tools or attachments.")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", model):
            raise _Failure("Configure an explicit AGY model ID.")
        if (not isinstance(executable, str) or not executable or "\x00" in executable
                or (os.path.sep in executable and not os.path.isabs(executable))):
            raise _Failure("Configure an AGY executable name or absolute path.")
        text = _prompt_text(body)
        return StreamingResponse(_stream(executable, model, public_model, text, self.valves.DEBUG_ACP_EVENTS,
                                                       self.valves.DEBUG_AGY_LOG_FILE,
                                                       self.valves.AGY_LOG_DIRECTORY),
                                 media_type="text/event-stream")
