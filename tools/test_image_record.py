#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for writing the image record of a local file or a hosted image, with no network.
"""

import hashlib
import io
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import image_record
import images
from test_images import PUBLIC, Network, Response, jpeg, png

HOSTED = "https://example.invalid/icon.png"
SHOT = "https://example.invalid/settings-window.jpg"


class ImageRecord(unittest.TestCase):
    def tool(self, *arguments, network=None):
        network = network or Network({}, {})
        with mock.patch("sys.stdout", io.StringIO()) as stdout, mock.patch("sys.stderr", io.StringIO()) as stderr:
            try:
                code = image_record.main(list(arguments), fetch=network.fetch)
            except SystemExit as stop:
                code = stop.code
        return code, stdout.getvalue(), stderr.getvalue()

    def local(self, data):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "icon.png"
        path.write_bytes(data)
        return str(path)

    def refused(self, *arguments, network=None):
        code, out, err = self.tool(*arguments, network=network)
        self.assertEqual((code, out), (1, ""))
        return err

    def test_a_local_png_prints_an_icon_record(self):
        data = png(512, 512)
        code, out, err = self.tool(self.local(data), "--icon", "--url", HOSTED)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(
            out,
            "[images.icon]\n"
            f'url = "{HOSTED}"\n'
            f'sha256 = "{hashlib.sha256(data).hexdigest()}"\n'
            "width = 512\n"
            "height = 512\n"
            f"size = {len(data)}\n",
        )

    def test_a_hosted_image_is_fetched_by_the_fetch_rules_and_keeps_its_url(self):
        data = jpeg(1600, 900)
        network = Network({"example.invalid": [PUBLIC]}, {SHOT: Response(200, data)})
        code, out, _ = self.tool(SHOT, "--description", "settings-window", network=network)
        self.assertEqual(code, 0)
        entries = tomllib.loads(out)["images"]["description"]
        self.assertEqual(
            entries,
            [{
                "id": "settings-window",
                "url": SHOT,
                "sha256": hashlib.sha256(data).hexdigest(),
                "width": 1600,
                "height": 900,
                "size": len(data),
            }],
        )
        self.assertEqual(list(entries[0]), ["id", "url", "sha256", "width", "height", "size"])
        self.assertEqual(network.connections, [("example.invalid", 443, PUBLIC)])

    def test_license_attribution_and_source_follow_the_facts(self):
        code, out, _ = self.tool(
            self.local(png(512, 512)), "--icon", "--url", HOSTED,
            "--license", "CC-BY-4.0",
            "--attribution", "Artwork by Example Artist",
            "--source", "https://example.invalid/original",
        )
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith(
            'license = "CC-BY-4.0"\n'
            'attribution = "Artwork by Example Artist"\n'
            'source = "https://example.invalid/original"\n'
        ))

    def test_text_is_escaped_so_the_record_parses_back(self):
        attribution = 'Art by "Kit" \\ José \U0001F680\tend'
        code, out, _ = self.tool(self.local(png(512, 512)), "--icon", "--url", HOSTED, "--attribution", attribution)
        self.assertEqual(code, 0)
        self.assertTrue(out.isascii())
        self.assertEqual(tomllib.loads(out)["images"]["icon"]["attribution"], attribution)

    def test_an_icon_outside_the_pixel_limits_prints_no_record(self):
        err = self.refused(self.local(png(128, 128)), "--icon", "--url", HOSTED)
        self.assertIn("128 by 128 pixels is outside", err)

    def test_a_local_file_above_the_cap_prints_no_record(self):
        err = self.refused(self.local(b"x" * (256 * 1024 + 1)), "--icon", "--url", HOSTED)
        self.assertIn("is larger than the cap of 262144 bytes", err)

    def test_a_hosted_image_above_the_cap_of_its_role_prints_no_record(self):
        network = Network({"example.invalid": [PUBLIC]}, {HOSTED: Response(200, b"x" * (256 * 1024 + 1))})
        err = self.refused(HOSTED, "--icon", network=network)
        self.assertIn("larger than the cap of 262144 bytes", err)

    def test_a_hosted_description_image_gets_the_cap_of_its_role(self):
        data = png(1600, 900) + b"\0" * 300000
        network = Network({"example.invalid": [PUBLIC]}, {SHOT: Response(200, data)})
        code, out, err = self.tool(SHOT, "--description", "settings-window", network=network)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tomllib.loads(out)["images"]["description"][0]["size"], len(data))

    def test_bytes_that_are_not_an_image_print_no_record(self):
        err = self.refused(self.local(b"<html></html>"), "--icon", "--url", HOSTED)
        self.assertIn("not PNG, JPEG or WebP", err)

    def test_a_license_that_is_not_on_the_spdx_list_prints_no_record(self):
        err = self.refused(self.local(png(512, 512)), "--icon", "--url", HOSTED, "--license", "Nope-1.0")
        self.assertIn("images.icon: license: 'Nope-1.0' names Nope-1.0, which is not on the SPDX license list", err)

    def test_a_source_that_is_not_https_prints_no_record(self):
        err = self.refused(
            self.local(png(512, 512)), "--icon", "--url", HOSTED, "--source", "http://example.invalid/original"
        )
        self.assertIn("images.icon: source: 'http://example.invalid/original' is not an https URL", err)

    def test_an_id_the_schema_refuses_prints_no_record(self):
        err = self.refused(self.local(png(512, 512)), "--description", "bad id!", "--url", HOSTED)
        self.assertIn("images.description: id: 'bad id!' is not 1 to 64 ASCII letters", err)

    def test_a_url_that_cannot_be_fetched_prints_no_record(self):
        err = self.refused(self.local(png(512, 512)), "--icon", "--url", "https://example.invalid:99999/icon.png")
        self.assertIn("images.icon: url: https://example.invalid:99999/icon.png names an invalid port", err)

    def test_a_host_that_does_not_answer_could_not_measure(self):
        network = Network({"example.invalid": [PUBLIC]}, {HOSTED: Response(503)})
        code, out, err = self.tool(HOSTED, "--icon", network=network)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("could not measure", err)

    def test_a_file_that_is_not_there_could_not_measure(self):
        missing = Path(self.local(b"")).with_name("not-there.png")
        code, out, err = self.tool(str(missing), "--icon", "--url", HOSTED)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("could not measure", err)

    def test_a_local_file_needs_a_url(self):
        code, _, err = self.tool(self.local(png(512, 512)), "--icon")
        self.assertEqual(code, 2)
        self.assertIn("needs --url", err)

    def test_a_hosted_image_takes_no_url(self):
        code, _, err = self.tool(HOSTED, "--icon", "--url", HOSTED)
        self.assertEqual(code, 2)
        self.assertIn("only for a local file", err)

    def test_a_role_is_required(self):
        code, _, err = self.tool(self.local(png(512, 512)), "--url", HOSTED)
        self.assertEqual(code, 2)
        self.assertIn("--icon", err)


if __name__ == "__main__":
    unittest.main()
