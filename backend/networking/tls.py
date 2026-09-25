import ssl
import os
from typing import Optional


def create_tls_context(certfile: Optional[str] = None, keyfile: Optional[str] = None) -> Optional[ssl.SSLContext]:
    if not certfile or not keyfile:
        return None

    if not os.path.exists(certfile) or not os.path.exists(keyfile):
        return None

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile, keyfile)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    return ctx


def create_tls_client_context(certfile: Optional[str] = None) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3

    if certfile and os.path.exists(certfile):
        ctx.load_verify_locations(certfile)
    else:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    return ctx
