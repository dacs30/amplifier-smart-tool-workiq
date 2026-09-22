"""Small newline-delimited JSON-RPC server used by MCP client tests."""

from __future__ import annotations

import json
import sys
import time


def send(message: dict) -> None:
    print(json.dumps(message, separators=(",", ":")), flush=True)


if "--hang" in sys.argv:
    time.sleep(30)
    raise SystemExit(0)

dropped_initialize = None
initialized = False

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        if method == "notifications/initialized":
            initialized = True
        continue

    if method == "initialize":
        if "--drop-first-initialize" in sys.argv and dropped_initialize is None:
            dropped_initialize = request_id
            continue
        if "--late-initialize-response" in sys.argv:
            send({"jsonrpc": "2.0", "id": dropped_initialize, "result": None})
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-workiq", "version": "1"},
                },
            }
        )
    elif method == "tools/list":
        if not initialized:
            raise SystemExit("Missing initialized notification")
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {"name": "ask", "inputSchema": {"type": "object"}},
                        {"name": "fetch", "inputSchema": {"type": "object"}},
                        {"name": "search_paths", "inputSchema": {"type": "object"}},
                        {"name": "get_schema", "inputSchema": {"type": "object"}},
                    ]
                },
            }
        )
    elif method == "tools/call":
        if not initialized:
            raise SystemExit("Missing initialized notification")
        params = message["params"]
        if params["name"] == "ask":
            response = {
                "response": f"Answer to: {params['arguments']['question']}",
                "conversationId": "conversation-1",
            }
            result = {
                "content": [{"type": "text", "text": json.dumps(response)}]
            }
        elif params["name"] == "search_paths":
            result = {
                "structuredContent": {
                    "paths": [
                        {
                            "path": "/me/messages",
                            "operations": ["fetch"],
                        }
                    ]
                }
            }
        elif params["name"] == "get_schema":
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": "type Message = { id: string; subject: string };",
                    }
                ]
            }
        else:
            result = {
                "structuredContent": {
                    "results": [
                        {
                            "statusCode": 200,
                            "data": {"value": [{"subject": "Example"}]},
                        }
                    ]
                }
            }
        send({"jsonrpc": "2.0", "id": request_id, "result": result})
