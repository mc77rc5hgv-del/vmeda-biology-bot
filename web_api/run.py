"""Serve the gateway on IPv4 (Railway healthchecks) and IPv6 (private RPC)."""
import logging
import os
import socket

import uvicorn

logger = logging.getLogger(__name__)


def _listener(port: int) -> socket.socket:
    """Dualstack IPv6+IPv4 on one socket where available (Railway); IPv4-only otherwise --
    a container/runner with IPv6 disabled entirely (seen on some GitHub-hosted runners and
    local sandboxes, see https://github.com/actions/runner-images/issues/668) would otherwise
    crash the whole gateway at startup for a capability (private RPC over IPv6) that's not on
    the critical path of serving Railway's own IPv4 healthchecks."""
    try:
        return socket.create_server(('::', port), family=socket.AF_INET6, dualstack_ipv6=True)
    except (ValueError, OSError):
        logger.warning('dualstack IPv6 unavailable on this host; falling back to IPv4-only')
        return socket.create_server(('0.0.0.0', port), family=socket.AF_INET)  # noqa: S104 -- must be reachable from outside the container (Railway healthchecks), same exposure as the dualstack '::' bind above


def main():
    port = int(os.environ.get('PORT', '8080'))
    with _listener(port) as listener:
        server = uvicorn.Server(uvicorn.Config('web_api.main:app', port=port, access_log=False))
        server.run(sockets=[listener])


if __name__ == '__main__':
    main()
