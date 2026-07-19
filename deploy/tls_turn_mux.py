"""Multiplex HTTPS/TLS and plaintext TURN-over-TCP on public port 8443.

TLS records begin with 0x16 and are forwarded to the internal HTTPS server.
TURN/STUN TCP frames begin with 0b00/0b01 and are forwarded to coturn.
This lets an SSH/IDE TCP port-forward carry both the web page and WebRTC relay.
"""

from __future__ import annotations

import asyncio
import logging
import os


LISTEN_HOST = os.getenv("MUX_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("MUX_PORT", "8443"))
HTTPS_TARGET = ("127.0.0.1", int(os.getenv("HTTPS_BACKEND_PORT", "9443")))
TURN_TARGET = ("127.0.0.1", int(os.getenv("TURN_BACKEND_PORT", "3478")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("tls-turn-mux")


async def _copy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.write_eof()
        except (ConnectionError, OSError, RuntimeError):
            pass


async def handle_client(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
) -> None:
    peer = client_writer.get_extra_info("peername")
    upstream_writer = None
    try:
        first = await asyncio.wait_for(client_reader.read(8192), timeout=10)
        if not first:
            return
        target = HTTPS_TARGET if first[0] == 0x16 else TURN_TARGET
        protocol = "https" if target == HTTPS_TARGET else "turn-tcp"
        upstream_reader, upstream_writer = await asyncio.open_connection(*target)
        upstream_writer.write(first)
        await upstream_writer.drain()
        logger.info("%s -> %s", peer, protocol)
        await asyncio.gather(
            _copy(client_reader, upstream_writer),
            _copy(upstream_reader, client_writer),
        )
    except (ConnectionError, asyncio.TimeoutError, OSError) as exc:
        logger.warning("connection %s failed: %s", peer, exc)
    finally:
        if upstream_writer is not None:
            upstream_writer.close()
            try:
                await upstream_writer.wait_closed()
            except (ConnectionError, OSError):
                pass
        client_writer.close()
        try:
            await client_writer.wait_closed()
        except (ConnectionError, OSError):
            pass


async def main() -> None:
    server = await asyncio.start_server(handle_client, LISTEN_HOST, LISTEN_PORT)
    addresses = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    logger.info("listening on %s (HTTPS -> %s, TURN/TCP -> %s)", addresses, HTTPS_TARGET, TURN_TARGET)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
