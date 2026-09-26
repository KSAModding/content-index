#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fetch the image of a record, and read what the bytes are, per RFC 0058.

The author chooses every URL, so a fetch goes over HTTPS only, follows at most
three redirects, resolves the host itself and connects only to a public address
it checked, sends no credentials or cookies, and stops reading at the byte cap
of the image's role. The format, the pixel size and the animation come from the
bytes, never from the extension or the Content-Type header.
"""

import hashlib
import http.client
import io
import ipaddress
import socket
import ssl
import struct
import time
import urllib.parse
from collections import namedtuple

USER_AGENT = "KSAModding-content-index-images"

MAX_REDIRECTS = 3
TIMEOUT = 10
DEADLINE = 30
CHUNK = 65536

REDIRECTS = (301, 302, 303, 307, 308)
MISSING = (404, 410)
TRANSIENT = (408, 425, 429)

ICON = "icon"
DESCRIPTION = "description"

# `high` bounds the shorter side when `ratio` is set, and each side otherwise.
Limits = namedtuple("Limits", "low high ratio cap")
LIMITS = {
    ICON: Limits(low=256, high=1024, ratio=2, cap=256 * 1024),
    DESCRIPTION: Limits(low=1, high=2048, ratio=None, cap=1024 * 1024),
}

PNG = "PNG"
JPEG = "JPEG"
WEBP = "WebP"

Facts = namedtuple("Facts", "format width height animated")

EMBEDS_IPV4 = (
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("::/96"),
    ipaddress.ip_network("::ffff:0:0:0/96"),
)

JPEG_FRAMES = frozenset(
    (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF)
)


class Invalid(Exception):
    """The image is wrong or not there, so its record rejects."""


class Unavailable(Exception):
    """The host gave no usable answer this run, so nothing is decided."""


def records(document):
    """Every image record of a parsed document, as (where, role, record)."""
    images = document.get("images")
    if not isinstance(images, dict):
        return []
    found = []
    icon = images.get(ICON)
    if isinstance(icon, dict):
        found.append((f"images.{ICON}", ICON, icon))
    entries = images.get(DESCRIPTION)
    if isinstance(entries, list):
        for index, record in enumerate(entries):
            if isinstance(record, dict):
                found.append((f"images.{DESCRIPTION}[{index}]", DESCRIPTION, record))
    return found


def public(address):
    """Whether `address` is a public unicast address, including any IPv4 address it embeds."""
    ip = ipaddress.ip_address(address)
    if ip.version == 6:
        embedded = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if embedded is None and any(ip in network for network in EMBEDS_IPV4):
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if embedded is not None and not public(str(embedded)):
            return False
        if ip.is_site_local:
            return False
    return ip.is_global and not ip.is_multicast


def resolve(host, port):
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as error:
        raise Unavailable(f"{host} does not resolve: {error}") from error
    return [answer[4][0] for answer in answers]


def countdown(deadline, timeout=TIMEOUT, clock=time.monotonic):
    """A function that gives the seconds one wait may take, and raises TimeoutError when none are left."""
    ends = clock() + deadline

    def remaining():
        left = ends - clock()
        if left <= 0:
            raise TimeoutError("the time limit for the image ran out")
        return min(timeout, left)

    return remaining


class BoundedReader(io.RawIOBase):
    """Reads a socket, and gives each wait only the time the fetch has left."""

    def __init__(self, sock, remaining):
        self.sock = sock
        self.remaining = remaining

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(self.remaining())
        return self.sock.recv_into(buffer)

    def makefile(self, mode):
        return io.BufferedReader(self)


class PinnedConnection(http.client.HTTPSConnection):
    """HTTPS to one checked address, with the certificate verified for the host name."""

    def __init__(self, host, port, address, remaining):
        tls = ssl.create_default_context()
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        super().__init__(host, port, context=tls)
        self.tls = tls
        self.address = address
        self.remaining = remaining

    def connect(self):
        raw = socket.create_connection((self.address, self.port), self.remaining())
        try:
            raw.settimeout(self.remaining())
            self.sock = self.tls.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise

    def response_class(self, sock, *arguments, **options):
        return http.client.HTTPResponse(BoundedReader(sock, self.remaining), *arguments, **options)


def target(url):
    """The host, port and request path of `url`. Raises Invalid when it may not be fetched."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() != "https":
        raise Invalid(f"{url} is not an https URL")
    if parts.username is not None or parts.password is not None:
        raise Invalid(f"{url} carries credentials")
    host = parts.hostname
    if not host or not host.isascii():
        raise Invalid(f"{url} names no host that can be fetched")
    try:
        port = parts.port or 443
    except ValueError as error:
        raise Invalid(f"{url} names an invalid port") from error
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return host, port, path


def fetch(url, cap, *, resolve=resolve, connect=PinnedConnection, clock=time.monotonic,
          timeout=TIMEOUT, deadline=DEADLINE):
    """The bytes at `url`, at most `cap` of them. Raises Invalid or Unavailable."""
    remaining = countdown(deadline, timeout, clock)
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        body, location = _request(current, cap, resolve, connect, remaining)
        if location is None:
            return body
        current = location
    raise Invalid(f"{url} is reached through more than {MAX_REDIRECTS} redirects")


def _request(url, cap, resolve, connect, remaining):
    host, port, path = target(url)
    addresses = resolve(host, port)
    if not addresses:
        raise Unavailable(f"{host} resolves to no address")
    for address in addresses:
        if not public(address):
            raise Invalid(f"{host} resolves to {address}, which is not a public address")

    try:
        connection = _open(host, port, addresses, connect, remaining)
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "image/png, image/jpeg, image/webp",
                    "Accept-Encoding": "identity",
                },
            )
            response = connection.getresponse()
            return _answer(url, response, cap, remaining)
        finally:
            connection.close()
    except ssl.SSLCertVerificationError as error:
        raise Invalid(f"{host} has a certificate that does not verify: {error}") from error
    except http.client.InvalidURL as error:
        raise Invalid(f"{url} cannot be requested: {error}") from error
    except (OSError, http.client.HTTPException) as error:
        raise Unavailable(f"{host} did not answer: {error!r}") from error


def _open(host, port, addresses, connect, remaining):
    failure = None
    for address in addresses:
        remaining()
        connection = connect(host, port, address, remaining)
        try:
            connection.connect()
            return connection
        except ssl.SSLCertVerificationError:
            connection.close()
            raise
        except OSError as error:
            connection.close()
            failure = error
    raise failure


def _answer(url, response, cap, remaining):
    status = response.status
    if status in REDIRECTS:
        location = response.getheader("Location")
        if not location:
            raise Invalid(f"{url} answered HTTP {status} with no Location")
        return None, urllib.parse.urljoin(url, location.strip())
    if status in MISSING:
        raise Invalid(f"{url} answered HTTP {status}, so the image is not there")
    if status in TRANSIENT or status >= 500:
        raise Unavailable(f"{url} answered HTTP {status}")
    if status != 200:
        raise Invalid(f"{url} answered HTTP {status}")

    encoding = (response.getheader("Content-Encoding") or "identity").strip().lower()
    if encoding != "identity":
        raise Invalid(f"{url} is served with Content-Encoding {encoding}, not as the image bytes")
    length = (response.getheader("Content-Length") or "").strip()
    if length.isdecimal() and int(length) > cap:
        raise Invalid(f"{url} is {length} bytes, above the cap of {cap}")

    body = bytearray()
    while True:
        remaining()
        chunk = response.read(min(CHUNK, cap + 1 - len(body)))
        if not chunk:
            return bytes(body), None
        body += chunk
        if len(body) > cap:
            raise Invalid(f"{url} is larger than the cap of {cap} bytes")


def inspect(data):
    """The format, pixel size and animation of `data`. Raises Invalid."""
    try:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return _png(data)
        if data.startswith(b"\xff\xd8\xff"):
            return _jpeg(data)
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return _webp(data)
    except struct.error as error:
        raise Invalid(f"the image ends early: {error}") from error
    raise Invalid("the bytes are not PNG, JPEG or WebP")


def _png(data):
    position = 8
    size = None
    animated = False
    pixels = False
    while position + 12 <= len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        body = data[position + 8:position + 8 + length]
        if len(body) < length:
            break
        if size is None:
            if kind != b"IHDR" or length != 13:
                raise Invalid("the PNG does not start with its header chunk")
            size = struct.unpack(">II", body[:8])
        elif kind == b"acTL":
            animated = True
        elif kind == b"IDAT":
            pixels = True
        elif kind == b"IEND":
            if not pixels:
                raise Invalid("the PNG carries no image data")
            return Facts(PNG, size[0], size[1], animated)
        position += 12 + length
    raise Invalid("the PNG ends before its IEND chunk")


def _jpeg(data):
    position = 2
    while position < len(data):
        if data[position] != 0xFF:
            raise Invalid("the JPEG has a broken marker")
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            continue
        if marker in (0xD9, 0xDA):
            break
        length = struct.unpack(">H", data[position:position + 2])[0]
        if length < 2:
            raise Invalid("the JPEG has a broken segment length")
        if marker in JPEG_FRAMES:
            height, width = struct.unpack(">HH", data[position + 3:position + 7])
            return Facts(JPEG, width, height, False)
        position += length
    raise Invalid("the JPEG names no frame size before its image data")


def _webp(data):
    end = 8 + struct.unpack("<I", data[4:8])[0]
    if end > len(data):
        raise Invalid("the WebP is shorter than its RIFF header says")
    position = 12
    canvas = None
    frame = None
    animated = False
    while position + 8 <= end:
        kind = data[position:position + 4]
        length = struct.unpack("<I", data[position + 4:position + 8])[0]
        if position + 8 + length > end:
            raise Invalid("a WebP chunk runs past the end of the file")
        body = data[position + 8:position + 8 + length]
        if kind == b"VP8X":
            if length < 10:
                raise Invalid("the WebP has a broken extended header")
            animated = animated or bool(body[0] & 0x02)
            canvas = (
                1 + int.from_bytes(body[4:7], "little"),
                1 + int.from_bytes(body[7:10], "little"),
            )
        elif kind in (b"ANIM", b"ANMF"):
            animated = True
        elif kind == b"VP8 " and frame is None:
            if length < 10 or body[3:6] != b"\x9d\x01\x2a":
                raise Invalid("the WebP has a broken lossy frame header")
            width, height = struct.unpack("<HH", body[6:10])
            frame = (width & 0x3FFF, height & 0x3FFF)
        elif kind == b"VP8L" and frame is None:
            if length < 5 or body[0] != 0x2F:
                raise Invalid("the WebP has a broken lossless header")
            bits = int.from_bytes(body[1:5], "little")
            frame = (1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF))
        position += 8 + length + (length & 1)

    if frame is None and not animated:
        raise Invalid("the WebP carries no image")
    width, height = canvas or frame or (0, 0)
    return Facts(WEBP, width, height, animated)


def outside_limits(role, width, height):
    """Why `width` by `height` pixels breaks the limits of `role`, or None when it does not."""
    limits = LIMITS[role]
    shorter, longer = sorted((width, height))
    if limits.ratio is None:
        if limits.low <= shorter and longer <= limits.high:
            return None
        return f"{width} by {height} pixels is outside {limits.low} to {limits.high} per side"
    if limits.low <= shorter <= limits.high and longer <= limits.ratio * shorter:
        return None
    return (
        f"{width} by {height} pixels is outside the limits: the shorter side "
        f"{limits.low} to {limits.high}, the longer side at most {limits.ratio} times the shorter side"
    )


def center_square(width, height):
    """The square a client shows of an icon, as (left, top, right, bottom) in pixels."""
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return left, top, left + side, top + side


def compare(record, role, data):
    """What differs between the bytes and the record, or breaks the role's limits."""
    facts = inspect(data)
    problems = []
    if facts.animated:
        problems.append(f"the {facts.format} is animated")
    outside = outside_limits(role, facts.width, facts.height)
    if outside:
        problems.append(outside)
    for key, found in (("width", facts.width), ("height", facts.height), ("size", len(data))):
        if record.get(key) != found:
            problems.append(f"{key} is {record.get(key)} and the bytes show {found}")
    digest = hashlib.sha256(data).hexdigest()
    if str(record.get("sha256") or "").lower() != digest:
        problems.append(f"sha256 is {record.get('sha256')} and the bytes show {digest}")
    return problems


def verify(record, role, fetch=fetch):
    """Fetch the image of one record and compare it. Raises Invalid or Unavailable."""
    data = fetch(record["url"], LIMITS[role].cap)
    problems = compare(record, role, data)
    if problems:
        raise Invalid("; ".join(problems))
