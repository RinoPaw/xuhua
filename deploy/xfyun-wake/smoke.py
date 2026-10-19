"""Use synthetic test PCM; never print host credentials or capture a microphone."""
import asyncio
import json
from pathlib import Path
import time

from websockets.asyncio.client import connect

TOKEN = dict(line.split('=', 1) for line in Path('/etc/xfyun-wake/service.env').read_text().splitlines() if '=' in line)['WAKE_SERVICE_TOKEN']
URL = 'ws://172.17.0.1:5052/api/wake'


async def main():
    async with connect(URL) as ws:
        await ws.send(json.dumps({'token': TOKEN}))
        first = json.loads(await ws.recv())
        assert first['type'] == 'ready', first
        stream = first['stream_id']
        results = []
        for name in ('long', 'short', 'question', 'negative'):
            if name != 'long':
                await ws.send(json.dumps({'type': 'resume'}))
                ready = json.loads(await ws.recv())
                assert ready['type'] == 'ready' and ready['stream_id'] != stream, ready
                stream = ready['stream_id']
            pcm = Path('/home/ubuntu/wake-deploy/' + name + '.pcm').read_bytes() + bytes(32000)
            pcm += bytes((-len(pcm)) % 640)
            start = time.monotonic()

            async def send():
                for offset in range(0, len(pcm), 640):
                    await asyncio.sleep(max(0, start + offset / 32000 - time.monotonic()))
                    await ws.send(pcm[offset:offset + 640])
            sender = asyncio.create_task(send())
            result = None
            try:
                result = json.loads(await asyncio.wait_for(ws.recv(), len(pcm) / 32000 + 1))
            except asyncio.TimeoutError:
                pass
            await sender
            print(json.dumps({'sample': name, 'event': result}, ensure_ascii=False), flush=True)
            if name == 'negative':
                assert result is None, result
            else:
                assert result and result['type'] == 'wake', (name, result)
                assert result['stream_id'] == stream
                assert 0 < result['end_sample'] <= len(pcm) / 2
            results.append({'sample': name, 'result': result})
        async with connect(URL) as busy:
            await busy.send(json.dumps({'token': TOKEN}))
            assert json.loads(await busy.recv())['code'] == 'wake_busy'
        # Production terminal leases remain alive beyond the old 120-second limit.
        await ws.send(json.dumps({'type': 'pause'}))
        assert json.loads(await ws.recv())['type'] == 'paused'
        for _ in range(9):
            await asyncio.sleep(15)
            await ws.send(json.dumps({'type': 'ping'}))
            assert json.loads(await ws.recv())['type'] == 'pong'
        await ws.send(json.dumps({'type': 'resume'}))
        assert json.loads(await ws.recv())['type'] == 'ready'
        print(json.dumps({'samples': results, 'busy_rejected': True, 'persistent_over_120s': True}, ensure_ascii=False))


asyncio.run(main())
