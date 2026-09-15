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

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        continue

    if method == "initialize":
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
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {"name": "ask", "inputSchema": {"type": "object"}},
                        {"name": "fetch", "inputSchema": {"type": "object"}},
                    ]
                },
            }
        )
    elif method == "tools/call":
        params = message["params"]
        if params["name"] == "ask":
            response = {
                "response": f"Answer to: {params['arguments']['question']}",
                "conversationId": "conversation-1",
            }
            result = {
                "content": [{"type": "text", "text": json.dumps(response)}]
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
