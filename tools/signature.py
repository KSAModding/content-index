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


def _decode(text):
    # The strict decoder refuses characters outside the standard alphabet and
    # a bad pad, and the encode round trip refuses a missing pad and nonzero
    # unused bits.
    raw = binascii.a2b_base64(text, strict_mode=True)
    if binascii.b2a_base64(raw, newline=False) != text:
        raise ValueError("not canonical base64")
    return raw


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
