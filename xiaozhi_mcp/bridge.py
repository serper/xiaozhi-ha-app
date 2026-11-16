"""Minimal stdio-to-Xiaozhi WebSocket MCP bridge with reconnect and child cleanup."""
import asyncio
import logging
import os
import sys

import websockets

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('xiaozhi-bridge')


async def connect_once(endpoint):
    # Never include endpoint (contains credentials) in logs/exceptions.
    async with websockets.connect(endpoint, max_size=2 * 1024 * 1024, ping_interval=25, ping_timeout=25) as ws:
        logger.info('Conectado a Xiaozhi; iniciando herramienta MCP')
        proc = await asyncio.create_subprocess_exec(
            sys.executable, '-u', '/app/weather.py',
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def ws_to_child():
            async for data in ws:
                if isinstance(data, bytes):
                    data = data.decode('utf-8')
                proc.stdin.write(data.rstrip('\n').encode('utf-8') + b'\n')
                await proc.stdin.drain()

        async def child_to_ws():
            while line := await proc.stdout.readline():
                await ws.send(line.decode('utf-8').rstrip('\n'))
            raise ConnectionError('El proceso MCP terminó')

        async def stderr_log():
            while line := await proc.stderr.readline():
                # Python MCP stderr only; avoid logging full remote request payloads.
                logger.info('MCP: %s', line.decode('utf-8', 'replace').strip()[:500])

        tasks = [asyncio.create_task(coro()) for coro in (ws_to_child, child_to_ws, stderr_log)]
        try:
            done, pending = await asyncio.wait(tasks[:2], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.exception():
                    raise task.exception()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()


async def run():
    endpoint = os.environ['MCP_ENDPOINT']
    delay = 1
    while True:
        try:
            await connect_once(endpoint)
            delay = 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Do not serialize exception: websockets errors may include token-bearing URI.
            logger.warning('Conexión interrumpida (%s); reconexión en %ds', type(exc).__name__, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60)


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info('Detenido')


if __name__ == '__main__':
    main()
