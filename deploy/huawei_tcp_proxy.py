#!/usr/bin/env python3
import argparse
import asyncio
import logging
import ssl
from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int


def parse_endpoint(value: str) -> Endpoint:
    host, separator, port = value.rpartition(":")
    if not separator or not host:
        raise argparse.ArgumentTypeError(f"invalid endpoint: {value}")
    try:
        parsed_port = int(port)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid port: {port}") from exc
    return Endpoint(host, parsed_port)


def parse_mapping(value: str) -> tuple[Endpoint, Endpoint]:
    listen, separator, upstream = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError(f"invalid mapping: {value}")
    return parse_endpoint(listen), parse_endpoint(upstream)


async def copy_stream(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.write_eof()
        except (AttributeError, ConnectionError, OSError):
            pass


async def proxy_connection(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream: Endpoint,
) -> None:
    peer = client_writer.get_extra_info("peername")
    try:
        upstream_reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection(upstream.host, upstream.port),
            timeout=10,
        )
    except (OSError, asyncio.TimeoutError) as exc:
        logging.warning(
            "%s -> %s:%s unavailable: %s",
            peer,
            upstream.host,
            upstream.port,
            exc,
        )
        client_writer.close()
        await client_writer.wait_closed()
        return

    logging.info("%s -> %s:%s connected", peer, upstream.host, upstream.port)
    try:
        await asyncio.gather(
            copy_stream(client_reader, upstream_writer),
            copy_stream(upstream_reader, client_writer),
        )
    finally:
        upstream_writer.close()
        client_writer.close()
        await asyncio.gather(
            upstream_writer.wait_closed(),
            client_writer.wait_closed(),
            return_exceptions=True,
        )


async def run(
    mapping_values: list[tuple[Endpoint, Endpoint]],
    tls_context: ssl.SSLContext | None,
) -> None:
    servers = []
    for listen, upstream in mapping_values:
        server = await asyncio.start_server(
            lambda reader, writer, target=upstream: proxy_connection(
                reader,
                writer,
                target,
            ),
            listen.host,
            listen.port,
            reuse_address=True,
            ssl=tls_context,
            ssl_handshake_timeout=10 if tls_context else None,
        )
        servers.append(server)
        logging.info(
            "listening on %s:%s -> %s:%s",
            listen.host,
            listen.port,
            upstream.host,
            upstream.port,
        )

    await asyncio.gather(*(server.serve_forever() for server in servers))


def main() -> None:
    parser = argparse.ArgumentParser(description="Persistent TCP forwarding proxy")
    parser.add_argument("--map", action="append", required=True, type=parse_mapping)
    parser.add_argument("--certfile")
    parser.add_argument("--keyfile")
    args = parser.parse_args()
    if bool(args.certfile) != bool(args.keyfile):
        parser.error("--certfile and --keyfile must be provided together")

    tls_context = None
    if args.certfile:
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
        tls_context.load_cert_chain(args.certfile, args.keyfile)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run(args.map, tls_context))


if __name__ == "__main__":
    main()
