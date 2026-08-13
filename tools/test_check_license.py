#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for resolving a license expression against the SPDX list.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_license


class Accepted(unittest.TestCase):
    def assert_ok(self, expression):
        self.assertEqual(check_license.errors_for(expression), [], expression)

    def test_a_plain_identifier(self):
        self.assert_ok("MIT")

    def test_a_compound_expression(self):
        self.assert_ok("(MIT OR Apache-2.0) AND CC0-1.0")

    def test_an_exception(self):
        self.assert_ok("GPL-2.0-or-later WITH Bison-exception-2.2")

    def test_the_or_later_operator(self):
        self.assert_ok("GPL-2.0+")

    def test_a_license_reference(self):
        self.assert_ok("LicenseRef-Kitten-1.0")

    def test_a_document_scoped_license_reference(self):
        self.assert_ok("DocumentRef-spdx-tool:LicenseRef-Kitten")

    def test_a_license_reference_inside_an_expression(self):
        self.assert_ok("MIT AND LicenseRef-Kitten-1.0")

    def test_the_licenses_the_repository_itself_uses(self):
        self.assert_ok("CC0-1.0")
        self.assert_ok("CC-BY-4.0")

    def test_an_absent_license_is_not_this_check_s_business(self):
        self.assertEqual(check_license.errors_for(None), [])
        self.assertEqual(check_license.errors_for(""), [])
        self.assertEqual(check_license.errors_for("   "), [])

    def test_a_license_that_is_not_a_string_is_left_to_the_schema(self):
        self.assertEqual(check_license.errors_for(7), [])


class Rejected(unittest.TestCase):
    def assert_rejected(self, expression, fragment):
        errors = check_license.errors_for(expression)
        self.assertTrue(errors, f"{expression!r} should have been rejected")
        self.assertTrue(
            any(fragment in error for error in errors),
            f"{expression!r} was rejected, but not for '{fragment}': {errors}",
        )

    def test_an_identifier_that_does_not_exist(self):
        self.assert_rejected("NotALicense-9.9", "not on the SPDX license list")

    def test_a_typo_in_a_real_identifier(self):
        self.assert_rejected("MTI", "MTI")

    def test_one_wrong_identifier_inside_a_compound_expression(self):
        self.assert_rejected("MIT AND NotALicense-9.9", "NotALicense-9.9")

    def test_a_reference_that_is_not_a_license_reference(self):
        self.assert_rejected("KittenRef-1.0", "KittenRef-1.0")

    def test_a_plain_license_used_as_an_exception(self):
        self.assert_rejected("MIT WITH MIT", "MIT")


class DoesNotCrash(unittest.TestCase):
    """The library raises several unrelated types on a broken expression.
    """

    def assert_survives(self, expression):
        errors = check_license.errors_for(expression)
        self.assertTrue(errors, f"{expression!r} should have been reported")

    def test_an_operator_with_nothing_on_its_right(self):
        self.assert_survives("MIT OR")

    def test_an_operator_with_nothing_on_its_left(self):
        self.assert_survives("AND MIT")

    def test_empty_parentheses(self):
        self.assert_survives("()")

    def test_an_unclosed_parenthesis(self):
        self.assert_survives("(MIT OR Apache-2.0")


class Document(unittest.TestCase):
    def test_the_error_names_the_document_and_the_field(self):
        errors = []
        check_license.check_document("listings/Mod.toml", {"license": "MTI"}, errors)
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("listings/Mod.toml: license: "))

    def test_a_valid_document_adds_nothing(self):
        errors = []
        check_license.check_document("listings/Mod.toml", {"license": "MIT"}, errors)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
