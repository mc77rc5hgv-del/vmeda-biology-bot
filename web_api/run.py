"""Serve the gateway on IPv4 (Railway healthchecks) and IPv6 (private RPC)."""
import os
import socket

import uvicorn


def main():
    port = int(os.environ.get('PORT', '8080'))
    with socket.create_server(('::', port), family=socket.AF_INET6, dualstack_ipv6=True) as listener:
        server = uvicorn.Server(uvicorn.Config('web_api.main:app', port=port, access_log=False))
        server.run(sockets=[listener])


if __name__ == '__main__':
    main()
