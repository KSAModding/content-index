#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify the Ed25519 signature of a data file of a share host (RFC 0104).

A share host without GitHub storage serves each data file with a detached
signature beside it, at the file's path with `.sig` appended. The signature is
the base64 Ed25519 signature of the file's exact bytes, and hosts.toml gives
the host's `key` as base64 of its SubjectPublicKeyInfo (spec/share-host.md,
rules 20 to 35).

The byte rules are strict, so that one text has one meaning. A key is padded
standard base64 of the 44-byte Ed25519 SubjectPublicKeyInfo and nothing else.
A signature is at most MAX_SIGNATURE bytes, whitespace around it is removed,
and the rest is padded standard base64 of exactly 64 bytes. The URL-safe
alphabet, a missing pad, a line break inside the text and bits that a
canonical encoder leaves zero are all refused.

A key whose point has a small order is refused too, because one fixed
signature is valid for every body under such a key, and anyone could sign for
the host. small_order_key reads this from the text alone, so check_hosts.py
refuses such a key with no package installed.

The cryptography package is imported inside the functions only. ownership.py
imports this module only for a host with `data`, so every other check and the
releases tools that import ownership.py still run on a runner that installs
nothing. A live read checks a signature by `key` only (rule 22), and
`retired_keys` exist only to check signatures that were recorded before. The
helper in content-index-releases tools/hosts.py follows the same rules.
"""

import binascii

MAX_SIGNATURE = 1024
KEY_BYTES = 44
SIGNATURE_BYTES = 64
# The 12 bytes before the point in an Ed25519 SubjectPublicKeyInfo.
KEY_PREFIX = bytes.fromhex("302a300506032b6570032100")

# The point encodings of small order that libsodium refuses. These are the
# identity, the points of order 2, 4 and 8, and the forms of 0 and 1 with y
# not reduced below p. Each is listed with the sign bit clear and set.
_SMALL_ORDER_BASES = (
    "0100000000000000000000000000000000000000000000000000000000000000",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
    "edffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
    "eeffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
)
SMALL_ORDER = frozenset(
    bytes.fromhex(base[:-2]) + bytes([int(base[-2:], 16) | sign])
    for base in _SMALL_ORDER_BASES
    for sign in (0x00, 0x80)
)


def _decode(text):
    # The strict decoder refuses characters outside the standard alphabet and
    # a bad pad, and the encode round trip refuses a missing pad and nonzero
    # unused bits.
    raw = binascii.a2b_base64(text, strict_mode=True)
    if binascii.b2a_base64(raw, newline=False) != text:
        raise ValueError("not canonical base64")
    return raw


def small_order_key(text):
    """Return True when the base64 SubjectPublicKeyInfo `text` holds an
    Ed25519 point of small order. Any other text gives False."""
    try:
        raw = binascii.a2b_base64(text.encode("ascii"), strict_mode=True)
    except (UnicodeEncodeError, binascii.Error):
        return False
    return len(raw) == KEY_BYTES and raw[:12] == KEY_PREFIX and raw[12:] in SMALL_ORDER


def load_key(text):
    """Return the Ed25519 public key that the base64 SubjectPublicKeyInfo
    `text` holds, or raise ValueError when `text` is not one."""
    from cryptography.exceptions import UnsupportedAlgorithm
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_der_public_key

    try:
        raw = _decode(text.encode("ascii"))
    except (UnicodeEncodeError, binascii.Error) as error:
        raise ValueError(f"the key is not base64: {error}") from None
    if len(raw) != KEY_BYTES:
        raise ValueError(f"the key has {len(raw)} bytes, not {KEY_BYTES}")
    if raw[:12] == KEY_PREFIX and raw[12:] in SMALL_ORDER:
        raise ValueError("the key is a small-order point")
    try:
        key = load_der_public_key(raw)
    except (ValueError, UnsupportedAlgorithm):
        key = None
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("the key is not an Ed25519 key")
    return key


def verify(key, body, signature_text):
    """Return True when `signature_text`, the text of a .sig file as str or
    bytes, is a valid signature by `key` over the exact bytes `body`."""
    from cryptography.exceptions import InvalidSignature

    if isinstance(signature_text, str):
        try:
            signature_text = signature_text.encode("ascii")
        except UnicodeEncodeError:
            return False
    if len(signature_text) > MAX_SIGNATURE:
        return False
    try:
        signature = _decode(signature_text.strip())
    except (binascii.Error, ValueError):
        return False
    if len(signature) != SIGNATURE_BYTES:
        return False
    try:
        key.verify(signature, body)
    except InvalidSignature:
        return False
    return True
