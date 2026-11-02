#!/usr/bin/env python3
"""Sends text through a running observer and waits until the reply appears.

    python3 observer_send.py <observer.sock> <text> [timeout_seconds]

Run as root (the observer accepts root and www-data only). Point the observer at a
dedicated session, never one a person is using. Exit status 0 when a new assistant
message arrived and the conversation went back to idle.
"""
import asyncio
import json
import sys
import time


async def request(path, operation):
    reader, writer = await asyncio.open_unix_connection(path, limit=4_194_304)
    writer.write((json.dumps(operation, ensure_ascii=False) + '\n').encode())
    await writer.drain()
    return reader, writer


async def next_snapshot(reader):
    while True:
        event = json.loads(await asyncio.wait_for(reader.readline(), 20))
        if event['type'] == 'error':
            raise SystemExit('observer error: ' + event['error'])
        if event['type'] == 'conversation':
            return event


async def main(path, text, timeout):
    reader, writer = await request(path, {'op': 'watch'})
    before = len((await next_snapshot(reader))['messages'])
    writer.close()
    reader, writer = await request(path, {'op': 'send', 'text': text})
    print('send:', (await reader.readline()).decode().strip())
    writer.close()
    reader, writer = await request(path, {'op': 'watch'})
    states, deadline = [], time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            snapshot = await next_snapshot(reader)
            if not states or states[-1] != snapshot['status']:
                states.append(snapshot['status'])
            messages = snapshot['messages']
            if len(messages) >= before + 2 and messages[-1]['role'] == 'assistant' and snapshot['status'] == 'idle':
                for message in messages[-2:]:
                    print(message['role'], '|', message['text'][:200])
                print('states:', ' -> '.join(states))
                return 0
    finally:
        writer.close()
    print('timed out; states:', ' -> '.join(states))
    return 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 120)))
