#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for fetching an image and reading its bytes, with no network.
"""

import hashlib
import http.client
import io
import socket
import ssl
import struct
import sys
import threading
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import images

PUBLIC = "93.184.216.34"
OTHER_PUBLIC = "93.184.216.35"


def png_chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png(width, height, animated=False):
    header = png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    control = png_chunk(b"acTL", struct.pack(">II", 2, 0)) if animated else b""
    return (
        b"\x89PNG\r\n\x1a\n"
        + header
        + control
        + png_chunk(b"IDAT", zlib.compress(b"\x00"))
        + png_chunk(b"IEND", b"")
    )


def jpeg(width, height):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    frame = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    scan = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00"
    return b"\xff\xd8" + app0 + frame + scan + b"\x00\xff\xd9"


def webp_chunk(kind, body):
    return kind + struct.pack("<I", len(body)) + body + (b"\x00" if len(body) % 2 else b"")


def webp(*chunks):
    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def lossy(width, height):
    return webp_chunk(b"VP8 ", b"\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", width, height))


def lossless(width, height):
    bits = (width - 1) | ((height - 1) << 14)
    return webp_chunk(b"VP8L", b"\x2f" + struct.pack("<I", bits))


def extended(width, height, animated=False):
    flags = 0x02 if animated else 0x00
    return webp_chunk(
        b"VP8X",
        bytes([flags, 0, 0, 0]) + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little"),
    )


class Response:
    def __init__(self, status, body=b"", headers=None):
        self.status = status
        self.body = io.BytesIO(body)
        self.headers = headers or {}
        self.served = 0

    def getheader(self, name, default=None):
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return default

    def read(self, amount):
        chunk = self.body.read(amount)
        self.served += len(chunk)
        return chunk


class Network:
    """DNS and HTTPS from two tables: host to addresses, URL to answer."""

    def __init__(self, addresses, answers):
        self.addresses = addresses
        self.answers = answers
        self.resolved = []
        self.connections = []
        self.requests = []

    def resolve(self, host, port):
        self.resolved.append(host)
        return self.addresses[host]

    def connect(self, host, port, address, timeout):
        network = self

        class Connection:
            def connect(self):
                network.connections.append((host, port, address))

            def request(self, method, path, headers):
                network.requests.append((method, host, path, headers))
                self.url = f"https://{host}{path}"

            def getresponse(self):
                answer = network.answers[self.url]
                if isinstance(answer, BaseException):
                    raise answer
                return answer

            def close(self):
                pass

        return Connection()

    def fetch(self, url, cap=1024, **options):
        return images.fetch(url, cap, resolve=self.resolve, connect=self.connect, **options)


def redirect(location, status=302):
    return Response(status, headers={"Location": location})


class Public(unittest.TestCase):
    def test_public_addresses(self):
        for address in (PUBLIC, "2606:4700::1111"):
            self.assertTrue(images.public(address), address)

    def test_addresses_that_are_not_public(self):
        for address in (
            "127.0.0.1",
            "::1",
            "10.1.2.3",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "fe80::1",
            "fd00:ec2::254",
            "100.100.100.200",
            "224.0.0.1",
            "ff02::1",
            "0.0.0.0",
            "::",
            "::ffff:127.0.0.1",
            "64:ff9b::7f00:1",
            "2002:7f00:1::",
            "::7f00:1",
            "::ffff:0:7f00:1",
            "fec0::1",
        ):
            self.assertFalse(images.public(address), address)


class Target(unittest.TestCase):
    def test_host_port_and_path(self):
        self.assertEqual(
            images.target("https://example.invalid:8443/a/b.png?x=1#part"),
            ("example.invalid", 8443, "/a/b.png?x=1"),
        )

    def test_http_is_invalid(self):
        with self.assertRaisesRegex(images.Invalid, "not an https URL"):
            images.target("http://example.invalid/a.png")

    def test_credentials_are_invalid(self):
        with self.assertRaisesRegex(images.Invalid, "carries credentials"):
            images.target("https://user:secret@example.invalid/a.png")


class Fetch(unittest.TestCase):
    def test_the_bytes_come_back(self):
        network = Network({"example.invalid": [PUBLIC]}, {"https://example.invalid/a.png": Response(200, b"image")})
        self.assertEqual(network.fetch("https://example.invalid/a.png"), b"image")

    def test_the_connection_goes_to_the_address_that_was_checked(self):
        network = Network({"example.invalid": [PUBLIC]}, {"https://example.invalid/a.png": Response(200, b"x")})
        network.fetch("https://example.invalid/a.png")
        self.assertEqual(network.connections, [("example.invalid", 443, PUBLIC)])

    def test_no_credentials_and_no_cookies_are_sent(self):
        network = Network({"example.invalid": [PUBLIC]}, {"https://example.invalid/a.png": Response(200, b"x")})
        network.fetch("https://example.invalid/a.png")
        sent = {name.lower() for name in network.requests[0][3]}
        self.assertFalse(sent & {"cookie", "authorization", "proxy-authorization"})

    def test_an_http_url_is_never_resolved(self):
        network = Network({}, {})
        with self.assertRaises(images.Invalid):
            network.fetch("http://example.invalid/a.png")
        self.assertEqual(network.resolved, [])

    def test_a_host_resolving_to_a_private_address_is_invalid_and_not_connected(self):
        network = Network({"inside.invalid": ["10.0.0.5"]}, {})
        with self.assertRaisesRegex(images.Invalid, "not a public address"):
            network.fetch("https://inside.invalid/a.png")
        self.assertEqual(network.connections, [])

    def test_one_private_address_among_public_ones_is_invalid(self):
        network = Network({"mixed.invalid": [PUBLIC, "127.0.0.1"]}, {})
        with self.assertRaisesRegex(images.Invalid, "127.0.0.1"):
            network.fetch("https://mixed.invalid/a.png")
        self.assertEqual(network.connections, [])

    def test_a_redirect_is_followed_and_its_host_checked_again(self):
        network = Network(
            {"example.invalid": [PUBLIC], "cdn.invalid": [OTHER_PUBLIC]},
            {
                "https://example.invalid/a.png": redirect("https://cdn.invalid/b.png"),
                "https://cdn.invalid/b.png": Response(200, b"moved"),
            },
        )
        self.assertEqual(network.fetch("https://example.invalid/a.png"), b"moved")
        self.assertEqual(network.resolved, ["example.invalid", "cdn.invalid"])
        self.assertEqual(network.connections[1], ("cdn.invalid", 443, OTHER_PUBLIC))

    def test_a_relative_redirect_stays_on_the_host(self):
        network = Network(
            {"example.invalid": [PUBLIC]},
            {
                "https://example.invalid/a.png": redirect("/b.png", 301),
                "https://example.invalid/b.png": Response(200, b"moved"),
            },
        )
        self.assertEqual(network.fetch("https://example.invalid/a.png"), b"moved")

    def test_a_redirect_to_a_private_address_is_invalid_and_not_connected(self):
        network = Network(
            {"example.invalid": [PUBLIC], "metadata.invalid": ["169.254.169.254"]},
            {"https://example.invalid/a.png": redirect("https://metadata.invalid/latest")},
        )
        with self.assertRaisesRegex(images.Invalid, "169.254.169.254"):
            network.fetch("https://example.invalid/a.png")
        self.assertEqual([address for _, _, address in network.connections], [PUBLIC])

    def test_a_redirect_to_http_is_invalid(self):
        network = Network(
            {"example.invalid": [PUBLIC]},
            {"https://example.invalid/a.png": redirect("http://example.invalid/a.png")},
        )
        with self.assertRaisesRegex(images.Invalid, "not an https URL"):
            network.fetch("https://example.invalid/a.png")

    def test_three_redirects_are_followed(self):
        answers = {f"https://example.invalid/{step}": redirect(f"/{step + 1}") for step in range(3)}
        answers["https://example.invalid/3"] = Response(200, b"end")
        network = Network({"example.invalid": [PUBLIC]}, answers)
        self.assertEqual(network.fetch("https://example.invalid/0"), b"end")

    def test_a_fourth_redirect_is_invalid(self):
        answers = {f"https://example.invalid/{step}": redirect(f"/{step + 1}") for step in range(4)}
        answers["https://example.invalid/4"] = Response(200, b"end")
        network = Network({"example.invalid": [PUBLIC]}, answers)
        with self.assertRaisesRegex(images.Invalid, "^https://example.invalid/0 is reached through more than 3 redirects"):
            network.fetch("https://example.invalid/0")
        self.assertEqual(len(network.requests), 4)

    def test_a_redirect_without_a_location_is_invalid(self):
        network = Network({"example.invalid": [PUBLIC]}, {"https://example.invalid/a.png": Response(302)})
        with self.assertRaisesRegex(images.Invalid, "no Location"):
            network.fetch("https://example.invalid/a.png")

    def test_a_body_above_the_cap_is_cut_off_while_it_streams(self):
        answer = Response(200, b"x" * 10_000)
        network = Network({"example.invalid": [PUBLIC]}, {"https://example.invalid/a.png": answer})
        with self.assertRaisesRegex(images.Invalid, "larger than the cap of 100 bytes"):
            network.fetch("https://example.invalid/a.png", cap=100)
        self.assertEqual(answer.served, 101)

    def test_a_body_at_the_cap_is_kept(self):
        network = Network({"example.invalid": [PUBLIC]}, {"https://example.invalid/a.png": Response(200, b"x" * 100)})
        self.assertEqual(len(network.fetch("https://example.invalid/a.png", cap=100)), 100)

    def test_a_declared_length_above_the_cap_is_invalid_before_reading(self):
        answer = Response(200, b"x" * 10, {"Content-Length": "5000"})
        network = Network({"example.invalid": [PUBLIC]}, {"https://example.invalid/a.png": answer})
        with self.assertRaisesRegex(images.Invalid, "above the cap"):
            network.fetch("https://example.invalid/a.png", cap=100)
        self.assertEqual(answer.served, 0)

    def test_a_compressed_body_is_invalid(self):
        answer = Response(200, b"x", {"Content-Encoding": "gzip"})
        network = Network({"example.invalid": [PUBLIC]}, {"https://example.invalid/a.png": answer})
        with self.assertRaisesRegex(images.Invalid, "gzip"):
            network.fetch("https://example.invalid/a.png")

    def test_a_missing_file_is_invalid(self):
        for status in (404, 410):
            network = Network({"example.invalid": [PUBLIC]}, {"https://example.invalid/a.png": Response(status)})
            with self.assertRaisesRegex(images.Invalid, "not there"):
                network.fetch("https://example.invalid/a.png")

    def test_a_server_error_or_a_rate_limit_is_unavailable(self):
        for status in (429, 500, 503):
            network = Network({"example.invalid": [PUBLIC]}, {"https://example.invalid/a.png": Response(status)})
            with self.assertRaises(images.Unavailable):
                network.fetch("https://example.invalid/a.png")

    def test_a_timeout_is_unavailable(self):
        network = Network({"example.invalid": [PUBLIC]}, {"https://example.invalid/a.png": TimeoutError("timed out")})
        with self.assertRaises(images.Unavailable):
            network.fetch("https://example.invalid/a.png")

    def test_a_refused_connection_is_unavailable(self):
        network = Network({"example.invalid": [PUBLIC]}, {"https://example.invalid/a.png": ConnectionRefusedError()})
        with self.assertRaises(images.Unavailable):
            network.fetch("https://example.invalid/a.png")

    def test_a_certificate_that_does_not_verify_is_invalid(self):
        failure = ssl.SSLCertVerificationError("certificate verify failed")
        network = Network({"example.invalid": [PUBLIC]}, {"https://example.invalid/a.png": failure})
        with self.assertRaisesRegex(images.Invalid, "certificate"):
            network.fetch("https://example.invalid/a.png")

    def test_a_body_that_takes_too_long_is_unavailable(self):
        now = [0]
        answer = Response(200, b"x" * 200_000)
        read = answer.read

        def slow(amount):
            now[0] += 20
            return read(amount)

        answer.read = slow
        network = Network({"example.invalid": [PUBLIC]}, {"https://example.invalid/a.png": answer})
        with self.assertRaisesRegex(images.Unavailable, "time limit"):
            network.fetch("https://example.invalid/a.png", cap=500_000, clock=lambda: now[0])
        self.assertEqual(answer.served, 2 * images.CHUNK)

    def test_the_time_limit_stops_trying_further_addresses(self):
        now = [0]
        attempts = []

        def connect(host, port, address, remaining):
            class Connection:
                def connect(self):
                    attempts.append(address)
                    now[0] += 20
                    raise ConnectionRefusedError()

                def close(self):
                    pass

            return Connection()

        addresses = [f"93.184.216.{last}" for last in range(1, 9)]
        with self.assertRaisesRegex(images.Unavailable, "time limit"):
            images.fetch(
                "https://example.invalid/a.png", 1024,
                resolve=lambda host, port: addresses, connect=connect, clock=lambda: now[0],
            )
        self.assertEqual(len(attempts), 2)

    def test_a_host_that_does_not_resolve_is_unavailable(self):
        with mock.patch.object(images.socket, "getaddrinfo", side_effect=images.socket.gaierror("no name")):
            with self.assertRaises(images.Unavailable):
                images.resolve("example.invalid", 443)


class PinnedConnection(unittest.TestCase):
    def test_the_socket_goes_to_the_checked_address_and_verifies_the_host_name(self):
        connection = images.PinnedConnection("example.invalid", 443, PUBLIC, lambda: 5)
        connection.tls = mock.Mock()
        with mock.patch.object(images.socket, "create_connection") as create:
            connection.connect()
        create.assert_called_once_with((PUBLIC, 443), 5)
        create.return_value.settimeout.assert_called_once_with(5)
        connection.tls.wrap_socket.assert_called_once_with(
            create.return_value, server_hostname="example.invalid"
        )

    def test_certificates_are_verified(self):
        tls = images.PinnedConnection("example.invalid", 443, PUBLIC, lambda: 5).tls
        self.assertEqual(tls.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(tls.check_hostname)

    def test_tls_before_1_2_is_refused_whatever_the_default(self):
        with mock.patch.object(images.ssl, "create_default_context", return_value=mock.Mock()):
            tls = images.PinnedConnection("example.invalid", 443, PUBLIC, lambda: 5).tls
        self.assertEqual(tls.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_the_response_reads_through_the_time_limit(self):
        connection = images.PinnedConnection("example.invalid", 443, PUBLIC, lambda: 5)
        response = connection.response_class(mock.Mock(), method="GET")
        self.assertIsInstance(response.fp.raw, images.BoundedReader)


class BoundedReader(unittest.TestCase):
    def test_a_peer_that_sends_one_byte_at_a_time_stops_at_the_time_limit(self):
        ours, theirs = socket.socketpair()
        self.addCleanup(ours.close)
        self.addCleanup(theirs.close)

        def trickle():
            try:
                theirs.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
                for _ in range(1000):
                    theirs.sendall(b"x")
                    time.sleep(0.01)
            except OSError:
                pass

        sender = threading.Thread(target=trickle, daemon=True)
        sender.start()
        started = time.monotonic()
        response = http.client.HTTPResponse(images.BoundedReader(ours, images.countdown(0.3)), method="GET")
        with self.assertRaises(TimeoutError):
            response.begin()
            response.read(1000)
        self.assertLess(time.monotonic() - started, 3)


class Inspect(unittest.TestCase):
    def test_png(self):
        self.assertEqual(images.inspect(png(512, 256)), images.Facts(images.PNG, 512, 256, False))

    def test_an_animated_png(self):
        self.assertTrue(images.inspect(png(512, 512, animated=True)).animated)

    def test_jpeg(self):
        self.assertEqual(images.inspect(jpeg(1600, 900)), images.Facts(images.JPEG, 1600, 900, False))

    def test_a_lossy_webp(self):
        self.assertEqual(images.inspect(webp(lossy(640, 480))), images.Facts(images.WEBP, 640, 480, False))

    def test_a_lossless_webp(self):
        self.assertEqual(images.inspect(webp(lossless(300, 200))), images.Facts(images.WEBP, 300, 200, False))

    def test_an_extended_webp_takes_the_canvas_size(self):
        facts = images.inspect(webp(extended(1024, 768), lossy(1024, 768)))
        self.assertEqual((facts.width, facts.height, facts.animated), (1024, 768, False))

    def test_an_animated_webp(self):
        data = webp(extended(512, 512, animated=True), webp_chunk(b"ANIM", b"\x00" * 6))
        self.assertTrue(images.inspect(data).animated)

    def test_an_animation_chunk_marks_a_webp_animated_without_the_flag(self):
        data = webp(extended(512, 512), webp_chunk(b"ANMF", b"\x00" * 16), lossy(512, 512))
        self.assertTrue(images.inspect(data).animated)

    def test_other_formats_are_invalid(self):
        for data in (b"GIF89a" + b"\x00" * 20, b"<svg xmlns='http://www.w3.org/2000/svg'/>", b""):
            with self.assertRaisesRegex(images.Invalid, "not PNG, JPEG or WebP"):
                images.inspect(data)

    def test_a_truncated_png_is_invalid(self):
        with self.assertRaises(images.Invalid):
            images.inspect(png(512, 512)[:40])

    def test_a_truncated_jpeg_is_invalid(self):
        with self.assertRaises(images.Invalid):
            images.inspect(jpeg(512, 512)[:24])

    def test_a_webp_shorter_than_its_header_says_is_invalid(self):
        with self.assertRaises(images.Invalid):
            images.inspect(webp(lossy(512, 512))[:-4])


def record_for(data, **changes):
    facts = images.inspect(data)
    record = {
        "url": "https://example.invalid/a",
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": facts.width,
        "height": facts.height,
        "size": len(data),
    }
    record.update(changes)
    return record


class Verify(unittest.TestCase):
    def verify(self, record, role, data):
        caps = []

        def fetch(url, cap):
            caps.append(cap)
            return data

        images.verify(record, role, fetch=fetch)
        return caps

    def test_a_matching_icon_passes_and_is_fetched_at_its_cap(self):
        data = png(512, 512)
        self.assertEqual(self.verify(record_for(data), images.ICON, data), [256 * 1024])

    def test_a_description_image_is_fetched_at_its_cap(self):
        data = jpeg(1600, 900)
        self.assertEqual(self.verify(record_for(data), images.DESCRIPTION, data), [1024 * 1024])

    def test_the_digest_compares_case_insensitively(self):
        data = png(512, 512)
        record = record_for(data)
        record["sha256"] = record["sha256"].upper()
        self.verify(record, images.ICON, data)

    def test_each_differing_fact_is_invalid(self):
        data = png(512, 512)
        for key, value in (("width", 513), ("height", 511), ("size", 1), ("sha256", "0" * 64)):
            with self.subTest(key=key), self.assertRaisesRegex(images.Invalid, f"{key} is"):
                self.verify(record_for(data, **{key: value}), images.ICON, data)

    def test_an_animated_image_is_invalid(self):
        data = webp(extended(512, 512, animated=True), webp_chunk(b"ANIM", b"\x00" * 6))
        with self.assertRaisesRegex(images.Invalid, "animated"):
            self.verify(record_for(data), images.ICON, data)

    def test_a_wide_icon_passes(self):
        data = png(1280, 640)
        self.verify(record_for(data), images.ICON, data)

    def test_a_tall_icon_passes(self):
        data = png(640, 1280)
        self.verify(record_for(data), images.ICON, data)

    def test_an_icon_at_each_pixel_limit_passes(self):
        for width, height in ((256, 256), (1024, 1024), (256, 512), (2048, 1024)):
            data = png(width, height)
            with self.subTest(width=width, height=height):
                self.verify(record_for(data), images.ICON, data)

    def test_an_icon_past_each_pixel_limit_is_invalid(self):
        for width, height in ((255, 510), (1025, 1025), (513, 256), (1024, 2049)):
            data = png(width, height)
            expected = (
                f"^{width} by {height} pixels is outside the limits: "
                "the shorter side 256 to 1024, the longer side at most 2 times the shorter side$"
            )
            with self.subTest(width=width, height=height), self.assertRaisesRegex(images.Invalid, expected):
                self.verify(record_for(data), images.ICON, data)

    def test_a_description_image_outside_the_limits_is_invalid(self):
        wide = png(4096, 100)
        with self.assertRaisesRegex(images.Invalid, "^4096 by 100 pixels is outside 1 to 2048 per side$"):
            self.verify(record_for(wide), images.DESCRIPTION, wide)

    def test_bytes_that_are_not_an_image_are_invalid(self):
        with self.assertRaisesRegex(images.Invalid, "not PNG, JPEG or WebP"):
            self.verify({"url": "https://example.invalid/a"}, images.ICON, b"<html></html>")


class CenterSquare(unittest.TestCase):
    def test_a_square_image_is_its_own_square(self):
        self.assertEqual(images.center_square(512, 512), (0, 0, 512, 512))

    def test_a_wide_image_is_cut_on_the_left_and_the_right(self):
        self.assertEqual(images.center_square(1280, 640), (320, 0, 960, 640))

    def test_a_tall_image_is_cut_at_the_top_and_the_bottom(self):
        self.assertEqual(images.center_square(640, 1280), (0, 320, 640, 960))

    def test_an_odd_difference_leaves_the_extra_pixel_on_the_right(self):
        self.assertEqual(images.center_square(1025, 256), (384, 0, 640, 256))

    def test_an_odd_difference_leaves_the_extra_pixel_at_the_bottom(self):
        self.assertEqual(images.center_square(256, 513), (0, 128, 256, 384))


class Records(unittest.TestCase):
    def test_every_record_with_its_place_and_role(self):
        document = {"images": {"icon": {"url": "i"}, "description": [{"id": "a"}, "junk", {"id": "b"}]}}
        self.assertEqual(
            [(where, role) for where, role, _ in images.records(document)],
            [
                ("images.icon", images.ICON),
                ("images.description[0]", images.DESCRIPTION),
                ("images.description[2]", images.DESCRIPTION),
            ],
        )

    def test_a_document_without_images_has_none(self):
        self.assertEqual(images.records({}), [])
        self.assertEqual(images.records({"images": "x"}), [])


if __name__ == "__main__":
    unittest.main()
