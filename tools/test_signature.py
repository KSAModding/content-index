#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the Ed25519 signature of a data file of a share host."""

import base64
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import signature

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

BODY = b'{"owner": "ksamods"}\n'


def seed(label):
    # A test key comes from a public label, so no private key file is kept.
    return hashlib.sha256(label.encode("ascii")).digest()


def spki(private):
    raw = private.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(raw).decode("ascii")


SIGNER = Ed25519PrivateKey.from_private_bytes(seed("content-index test signer"))
OTHER = Ed25519PrivateKey.from_private_bytes(seed("content-index test other"))
SIGNATURE = base64.b64encode(SIGNER.sign(BODY)).decode("ascii")


class Signature(unittest.TestCase):
    def setUp(self):
        self.key = signature.load_key(spki(SIGNER))

    def test_a_valid_signature_verifies(self):
        self.assertTrue(signature.verify(self.key, BODY, SIGNATURE))
        self.assertTrue(signature.verify(self.key, BODY, SIGNATURE.encode("ascii")))

    def test_a_trailing_newline_is_accepted(self):
        self.assertTrue(signature.verify(self.key, BODY, SIGNATURE + "\n"))

    def test_a_changed_byte_fails(self):
        self.assertFalse(signature.verify(self.key, BODY.replace(b"k", b"K", 1), SIGNATURE))

    def test_a_wrong_key_fails(self):
        self.assertFalse(signature.verify(signature.load_key(spki(OTHER)), BODY, SIGNATURE))

    def test_a_63_byte_signature_fails(self):
        short = base64.b64encode(SIGNER.sign(BODY)[:63]).decode("ascii")
        self.assertFalse(signature.verify(self.key, BODY, short))

    def test_the_url_safe_alphabet_fails(self):
        self.assertRegex(SIGNATURE, "[+/]")
        urlsafe = SIGNATURE.replace("+", "-").replace("/", "_")
        self.assertFalse(signature.verify(self.key, BODY, urlsafe))
        key = spki(SIGNER)
        self.assertRegex(key, "[+/]")
        with self.assertRaises(ValueError):
            signature.load_key(key.replace("+", "-").replace("/", "_"))

    def test_an_embedded_newline_fails(self):
        self.assertFalse(signature.verify(self.key, BODY, SIGNATURE[:40] + "\n" + SIGNATURE[40:]))
        with self.assertRaises(ValueError):
            signature.load_key(spki(SIGNER)[:20] + "\n" + spki(SIGNER)[20:])

    def test_an_x25519_key_is_refused(self):
        with self.assertRaises(ValueError):
            signature.load_key(spki(X25519PrivateKey.from_private_bytes(seed("x25519"))))


if __name__ == "__main__":
    unittest.main()
