"""Container healthcheck for the MCMA central server.

Requests GET /ready over HTTPS with FULL certificate verification: the
server certificate is checked against a trust file (default: the server
certificate itself, or MCMA_HEALTHCHECK_CA_FILE for an internal CA) and
against the name in MCMA_HEALTHCHECK_SERVER_NAME -- a name/IP that appears in
the certificate. Verification is never disabled; the connection goes to the
container's own address while the certificate is matched against the
configured name, which is how a probe reaches the service without weakening
TLS.

Exit 0 only when /ready answers 200. Prints one short line, never a
certificate, path contents or response body.
"""

import http.client
import os
import ssl
import sys


def main() -> int:
    host = os.environ["MCMA_API_HOST"]
    port = int(os.environ.get("MCMA_API_PORT", "8443"))
    server_name = os.environ.get("MCMA_HEALTHCHECK_SERVER_NAME") or host
    trust_file = os.environ.get("MCMA_HEALTHCHECK_CA_FILE") or os.environ["MCMA_TLS_CERT_PATH"]

    context = ssl.create_default_context(cafile=trust_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # A leaf certificate used as its own trust anchor (self-signed / dev) needs
    # partial-chain acceptance; the signature, validity and name checks stay on.
    context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT

    try:
        import socket

        raw = socket.create_connection((host, port), timeout=5)
        tls = context.wrap_socket(raw, server_hostname=server_name)
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.sock = tls
        connection.request("GET", "/ready", headers={"Host": server_name})
        status = connection.getresponse().status
        connection.close()
    except Exception as exc:  # any failure = unhealthy; type only, no details
        print(f"unhealthy: {type(exc).__name__}")
        return 1
    print(f"ready={status}")
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
