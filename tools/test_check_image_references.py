#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for resolving the images a description shows.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_image_references


def check(description, ids=()):
    document = {"description": description}
    if ids:
        document["images"] = {"description": [{"id": identifier} for identifier in ids]}
    errors = []
    notes = []
    check_image_references.check_document("listings/Mod.toml", document, errors, notes)
    return errors, notes


class References(unittest.TestCase):
    def test_a_reference_to_a_record_resolves(self):
        self.assertEqual(check("![The settings](ksa-image:settings-window)", ["settings-window"]), ([], []))

    def test_a_reference_to_an_id_with_no_record_rejects(self):
        errors, _ = check("![x](ksa-image:missing)", ["other"])
        self.assertIn("listings/Mod.toml: description: 'ksa-image:missing' names no record", errors[0])

    def test_a_reference_without_any_images_table_rejects(self):
        errors, _ = check("![x](ksa-image:missing)")
        self.assertEqual(len(errors), 1)

    def test_ids_are_case_sensitive(self):
        errors, _ = check("![x](ksa-image:Shot)", ["shot"])
        self.assertEqual(len(errors), 1)

    def test_a_reference_style_image_resolves(self):
        self.assertEqual(check("![x][shot]\n\n[shot]: ksa-image:shot\n", ["shot"]), ([], []))

    def test_an_image_inside_a_link_resolves(self):
        self.assertEqual(check("[![x](ksa-image:shot)](https://example.invalid/)", ["shot"]), ([], []))

    def test_an_image_in_a_code_block_is_not_an_image(self):
        errors, notes = check("```\n![x](ksa-image:missing)\n![y](https://example.invalid/y.png)\n```\n\n    ![z](ksa-image:gone)\n")
        self.assertEqual((errors, notes), ([], []))


class Warnings(unittest.TestCase):
    def test_a_record_that_nothing_references_warns(self):
        errors, notes = check("No images here.", ["shot"])
        self.assertEqual(errors, [])
        self.assertEqual(
            notes,
            ["listings/Mod.toml: images.description[0]: nothing in the description references 'shot', so no client shows it"],
        )

    def test_a_link_to_a_record_is_not_a_reference(self):
        _, notes = check("[see](ksa-image:shot)", ["shot"])
        self.assertEqual(len(notes), 1)

    def test_an_image_with_another_destination_warns(self):
        errors, notes = check("![x](https://example.invalid/x.png)")
        self.assertEqual(errors, [])
        self.assertIn("the image 'https://example.invalid/x.png' is not a ksa-image: reference", notes[0])

    def test_an_image_with_a_script_destination_still_warns(self):
        _, notes = check("![x](javascript:alert(1))")
        self.assertEqual(len(notes), 1)

    def test_an_image_in_raw_html_warns(self):
        _, inline = check('Text <img src="https://example.invalid/x.png"> text')
        _, block = check('<div>\n<IMG src="https://example.invalid/x.png">\n</div>\n')
        self.assertIn("1 image(s) in raw HTML", inline[0])
        self.assertIn("1 image(s) in raw HTML", block[0])

    def test_a_document_without_a_description_only_reports_its_records(self):
        errors = []
        notes = []
        check_image_references.check_document("listings/Mod.toml", {"images": {"description": [{"id": "a"}]}}, errors, notes)
        self.assertEqual(errors, [])
        self.assertEqual(len(notes), 1)


if __name__ == "__main__":
    unittest.main()
