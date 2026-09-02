"""Minimal mock AI server for local development and manual testing.

Implements the robot<->server WebSocket protocol described in
docs/superpowers/specs/2026-09-02-haro-robot-design.md with a canned
response, so the Haro pipeline can be exercised end-to-end before the
real AI server exists.
"""
import asyncio
import json
import math
import struct

import websockets

SAMPLE_RATE = 24000


def _make_tone(duration_s: float, frequency_hz: float) -> bytes:
    num_samples = int(SAMPLE_RATE * duration_s)
    samples = [
        int(32767 * 0.3 * math.sin(2 * math.pi * frequency_hz * i / SAMPLE_RATE))
        for i in range(num_samples)
    ]
    return struct.pack(f"<{num_samples}h", *samples)


async def handle_connection(websocket):
    async for message in websocket:
        if isinstance(message, str):
            data = json.loads(message)
            if data.get("type") == "end_of_speech":
                await websocket.send(json.dumps({"type": "emotion", "value": "happy"}))
                tone = _make_tone(duration_s=1.0, frequency_hz=440.0)
                chunk_size = 4096
                for i in range(0, len(tone), chunk_size):
                    await websocket.send(tone[i : i + chunk_size])
                await websocket.send(json.dumps({"type": "response_end"}))
        # Binary audio frames sent by the robot while listening are ignored by this mock.


async def main() -> None:
    async with websockets.serve(handle_connection, "0.0.0.0", 8765):
        print("Fake Haro server listening on ws://0.0.0.0:8765")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
