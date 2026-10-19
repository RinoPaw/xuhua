"""One persistent native engine, one owning terminal, explicit pause/resume."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import secrets
import struct
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse

BASE = Path(__file__).resolve().parent
SERVICE_TOKEN = os.environ['WAKE_SERVICE_TOKEN']
TEST_TOKEN = os.environ.get('WAKE_TEST_TOKEN', '')
KEYWORDS = ['叙华', '你好叙华']
lock = asyncio.Lock()
state = {'ready': False, 'busy': False, 'error': None}


class Engine:
    process = None
    reader = None
    queue = None
    active = False
    stream = ''

    def __init__(self):
        self.ready = asyncio.Event()

    async def start(self):
        self.ready.clear()
        state.update(ready=False, error=None)
        self.process = await asyncio.create_subprocess_exec(
            str(BASE / 'wake-worker'), cwd='/var/lib/xfyun-wake',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        self.reader = asyncio.create_task(self.read())
        await asyncio.wait_for(self.ready.wait(), 30)
        if not state['ready']:
            raise RuntimeError('wake_engine_unavailable')

    async def read(self):
        try:
            while line := await self.process.stdout.readline():
                result = json.loads(line)
                if result.get('type') == 'ready':
                    state.update(ready=True, error=None)
                    self.ready.set()
                elif result.get('type') == 'error':
                    state.update(ready=False, error={'code': result.get('code')})
                    self.ready.set()
                    if self.queue:
                        self.queue.put_nowait({'type': 'error', 'code': 'wake_engine_failed'})
                elif result.get('type') == 'wake' and self.active and self.queue:
                    for item in result.get('result', {}).get('rlt', []):
                        keyword = item.get('keyword')
                        if keyword not in KEYWORDS:
                            continue
                        # AIKit positions are 10 ms frames; 16 kHz = 160 samples/frame.
                        end = (int(item['istart']) + int(item['iduration'])) * 160
                        self.queue.put_nowait({'type': 'wake', 'keyword': keyword,
                                               'end_sample': end, 'stream_id': self.stream})
                        self.active = False
                        break
        finally:
            state['ready'] = False
            self.ready.set()
            if self.queue:
                with contextlib.suppress(asyncio.QueueFull):
                    self.queue.put_nowait({'type': 'error', 'code': 'wake_engine_failed'})

    async def reset(self):
        self.active = False
        if self.process is None or self.process.returncode is not None or not state['ready']:
            await self.stop()
            await self.start()
        self.ready.clear()
        self.process.stdin.write(struct.pack('<I', 0))
        await self.process.stdin.drain()
        await asyncio.wait_for(self.ready.wait(), 5)
        if not state['ready']:
            raise RuntimeError('wake_engine_unavailable')
        if self.queue:
            while not self.queue.empty():
                self.queue.get_nowait()
        self.stream = secrets.token_hex(8)
        self.active = True
        return {'type': 'ready', 'sample_rate': 16000, 'keywords': KEYWORDS,
                'stream_id': self.stream}

    async def write(self, pcm):
        self.process.stdin.write(struct.pack('<I', len(pcm)) + pcm)
        await self.process.stdin.drain()

    async def stop(self):
        self.active = False
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
        if self.process and self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()


engine = Engine()


@asynccontextmanager
async def lifespan(app):
    await engine.start()
    yield
    await engine.stop()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get('/')
async def index():
    return FileResponse(BASE / 'index.html', headers={'Cache-Control': 'no-store'})


@app.get('/capture.js')
async def capture():
    return FileResponse(BASE / 'capture.js', media_type='text/javascript')


@app.get('/healthz')
async def health():
    return {**state, 'service': 'xfyun-wake', 'keywords': KEYWORDS, 'sample_rate': 16000}


@app.websocket('/api/wake')
async def wake(ws: WebSocket):
    if ws.headers.get('origin') not in (None, 'https://xuhuaai.top'):
        await ws.close(code=1008)
        return
    await ws.accept()
    tasks = []
    try:
        hello = await asyncio.wait_for(ws.receive_json(), 5)
        candidate = str(hello.get('token', ''))
        production = secrets.compare_digest(candidate, SERVICE_TOKEN)
        if not production and not (TEST_TOKEN and secrets.compare_digest(candidate, TEST_TOKEN)):
            await ws.close(code=1008)
            return
        if lock.locked():
            await ws.send_json({'type': 'error', 'code': 'wake_busy', 'message': '语音服务正被另一终端使用。'})
            await ws.close(code=1013)
            return
        async with lock:
            state['busy'] = True
            queue = asyncio.Queue(maxsize=8)
            engine.queue = queue
            try:
                await ws.send_json(await engine.reset())
                started = time.monotonic()
                count = 0

                async def receive():
                    nonlocal started, count
                    while True:
                        message = await asyncio.wait_for(ws.receive(), 40)
                        if message['type'] == 'websocket.disconnect':
                            return
                        pcm = message.get('bytes')
                        if pcm is not None:
                            if not pcm or len(pcm) > 6400 or len(pcm) % 2:
                                raise ValueError('invalid_pcm')
                            count += len(pcm)
                            if count > (time.monotonic() - started + 3) * 32000:
                                raise ValueError('audio_rate_limit')
                            if engine.active:
                                await engine.write(pcm)
                        else:
                            control = json.loads(message.get('text', ''))
                            if control.get('type') == 'ping':
                                await queue.put({'type': 'pong'})
                            elif control.get('type') == 'pause':
                                engine.active = False
                                await queue.put({'type': 'paused'})
                            elif control.get('type') == 'resume':
                                while not queue.empty():
                                    queue.get_nowait()
                                await queue.put(await engine.reset())
                                started, count = time.monotonic(), 0
                            else:
                                raise ValueError('invalid_control')

                async def send():
                    while True:
                        await ws.send_json(await queue.get())

                tasks = [asyncio.create_task(receive()), asyncio.create_task(send())]
                await asyncio.wait(tasks, timeout=None if production else 120,
                                   return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                engine.active = False
                engine.queue = None
                state['busy'] = False
    except Exception:
        with contextlib.suppress(Exception):
            await ws.send_json({'type': 'error', 'code': 'wake_unavailable'})
    finally:
        with contextlib.suppress(Exception):
            await ws.close()
