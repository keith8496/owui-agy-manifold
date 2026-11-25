#!/usr/bin/env python3
"""Small stdio ACP peer controlled through FAKE_ACP_* environment variables."""
import json
import os
import sys
import time


def record(message):
    path = os.environ.get("FAKE_ACP_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(message) + "\n")


def send(message):
    print(json.dumps(message), flush=True)


def result(request, value):
    send({"jsonrpc": "2.0", "id": request["id"], "result": value})


record({"event": "started", "pid": os.getpid(), "argv": sys.argv[1:]})
scenario = os.environ.get("FAKE_ACP_SCENARIO", "stream")
for line in sys.stdin:
    request = json.loads(line)
    record(request)
    method = request.get("method")
    if method == "initialize":
        result(request, {"protocolVersion": 1, "agentCapabilities": {}})
    elif method == "session/new":
        result(request, {"sessionId": "fake-session", "models": {
            "currentModelId": "model-a", "availableModels": [
                {"modelId": "model-a", "name": "Model A"},
                {"modelId": "model-b", "name": "Model B"}]}})
    elif method in ("session/set_model", "session/set_config_option"):
        if scenario == "model_error":
            send({"jsonrpc": "2.0", "id": request["id"], "error":
                  {"code": -32602, "message": "model unavailable"}})
        else:
            result(request, {})
    elif method == "session/prompt":
        if scenario == "timeout":
            time.sleep(60)
        elif scenario == "permission":
            send({"jsonrpc": "2.0", "id": 991, "method": "session/request_permission",
                  "params": {"sessionId": "fake-session", "toolCall": {"toolCallId": "tool-1", "title": "unsafe"},
                             "options": [{"optionId": "allow", "kind": "allow_once", "name": "Allow"},
                                         {"optionId": "reject", "kind": "reject_once", "name": "Reject"}]}})
            response = json.loads(sys.stdin.readline())
            record(response)
            result(request, {"stopReason": "end_turn"})
        else:
            for text in ("hello ", "world"):
                send({"jsonrpc": "2.0", "method": "session/update", "params": {
                    "sessionId": "fake-session", "update": {"sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": text}}}})
            result(request, {"stopReason": "end_turn"})
