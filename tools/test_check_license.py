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

    def test_several_licenses_that_all_apply(self):
        self.assert_ok("GPL-2.0-only AND CC-BY-SA-4.0")

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

    def test_several_licenses_joined_by_a_comma(self):
        self.assert_rejected("GPL-2.0, CC BY-SA 4.0", "join several licenses with AND or OR")

    def test_an_unknown_identifier_points_at_the_list(self):
        self.assert_rejected("CC-BY-SA", check_license.SPDX_LIST)

    def test_two_licenses_with_no_operator_between_them(self):
        self.assert_rejected("MIT Apache-2.0", "no operator between them")

    def test_a_license_without_a_version_names_the_close_ids(self):
        self.assertEqual(
            check_license.errors_for("GPL"),
            [
                "'GPL' names GPL, which is not on the SPDX license list; ids close to GPL are "
                "GPL-1.0-only, GPL-2.0-only, GPL-3.0-only, GPL-1.0-or-later, GPL-2.0-or-later "
                "and GPL-3.0-or-later; the identifiers are at https://spdx.org/licenses/"
            ],
        )

    def test_no_short_name_of_the_library_passes(self):
        for name in check_license.NOT_SPDX:
            with self.subTest(name=name):
                self.assertFalse(check_license.known(name))
                self.assertTrue(check_license.errors_for(name), name)

    def test_the_short_names_are_still_in_the_library(self):
        # When an update of license-expression drops one, NOT_SPDX can lose it too.
        names = {
            name
            for entry in check_license.get_license_index()
            for name in entry.get("other_spdx_license_keys") or []
        }
        self.assertLessEqual(check_license.NOT_SPDX, names)

    def test_one_close_id_is_named_alone(self):
        self.assert_rejected("CC0", "; the id close to CC0 is CC0-1.0;")

    def test_close_ids_come_from_the_letters_at_the_start(self):
        self.assert_rejected("Apache2", "ids close to Apache2 are Apache-1.0, Apache-1.1 and Apache-2.0;")
        self.assert_rejected("GPLv3", "ids close to GPLv3 are GPL-1.0-only, GPL-2.0-only, GPL-3.0-only,")
        self.assert_rejected("MIT+", "ids close to MIT+ are MIT, MIT-0,")

    def test_a_name_with_spaces_finds_its_id(self):
        self.assert_rejected("CC BY-SA 4.0", "the id close to CC BY-SA 4.0 is CC-BY-SA-4.0;")

    def test_close_ids_are_current_and_at_most_six(self):
        found = check_license.close_ids("BSD", check_license.current_ids())
        self.assertEqual(len(found), check_license.CLOSE_LIMIT)
        self.assertNotIn("GPL-3.0", check_license.close_ids("GPL", check_license.current_ids()))

    def test_a_name_with_nothing_close_keeps_the_short_message(self):
        self.assertEqual(
            check_license.errors_for("Foo"),
            ["'Foo' names Foo, which is not on the SPDX license list; the identifiers are at https://spdx.org/licenses/"],
        )

    def test_aliases_that_are_not_spdx_ids_are_refused(self):
        self.assert_rejected("Verbatim-man-pages", "names Verbatim-man-pages, which is not on the SPDX license list")
        self.assert_rejected(
            "GPL-2.0-only WITH Assembly-exception",
            "names Assembly-exception, which is not on the SPDX license list",
        )

    def test_a_deprecated_spdx_exception_still_passes(self):
        self.assertEqual(check_license.errors_for("GPL-2.0-only WITH Nokia-Qt-exception-1.1"), [])

    def test_a_license_place_gets_no_exception_as_a_close_id(self):
        for name in ("LLVM", "Classpath"):
            with self.subTest(name=name):
                errors = check_license.errors_for(name)
                self.assertTrue(errors)
                self.assertFalse(any("exception" in error for error in errors), errors)

    def test_the_place_after_with_gets_exceptions_as_close_ids(self):
        self.assert_rejected(
            "GPL-2.0-only WITH Classpath", "the id close to Classpath is Classpath-exception-2.0;"
        )
        self.assert_rejected("GPL-2.0-only with LLVM", "the id close to LLVM is LLVM-exception;")

    def test_the_close_id_lists_keep_licenses_and_exceptions_apart(self):
        licenses = set(check_license.current_ids())
        exceptions = set(check_license.current_ids(exceptions=True))
        self.assertIn("MIT", licenses)
        self.assertIn("LLVM-exception", exceptions)
        self.assertFalse(licenses & exceptions)

    def test_a_known_name_in_the_wrong_place_gets_no_close_ids(self):
        errors = check_license.errors_for("MIT Classpath-exception-2.0")
        self.assertFalse(any("close to" in error for error in errors), errors)

    def test_a_license_and_a_license_reference_with_no_operator_between_them(self):
        self.assert_rejected("MIT LicenseRef-MyModLicense", "no operator between them")

    def test_a_license_reference_and_a_license_with_no_operator_between_them(self):
        self.assert_rejected("LicenseRef-MyModLicense MIT", "no operator between them")

    def test_two_license_references_with_no_operator_between_them(self):
        self.assert_rejected(
            "LicenseRef-MyModLicense LicenseRef-OtherLicense", "no operator between them"
        )

    def test_a_missing_operator_is_not_reported_as_an_unknown_identifier(self):
        expressions = (
            "MIT Apache-2.0",
            "MIT LicenseRef-MyModLicense",
            "LicenseRef-MyModLicense MIT",
            "LicenseRef-MyModLicense LicenseRef-OtherLicense",
        )
        for expression in expressions:
            errors = check_license.errors_for(expression)
            self.assertFalse(any("SPDX license list" in error for error in errors), errors)

    def test_an_exception_where_a_license_belongs(self):
        self.assert_rejected("MIT Classpath-exception-2.0", "Classpath-exception-2.0")

    def test_a_second_exception_after_the_one_with_names(self):
        self.assert_rejected(
            "GPL-2.0-only WITH Classpath-exception-2.0 Autoconf-exception-2.0",
            "Autoconf-exception-2.0",
        )

    def test_an_exception_out_of_place_keeps_the_list_message(self):
        expressions = (
            "MIT Classpath-exception-2.0",
            "GPL-2.0-only WITH Classpath-exception-2.0 Autoconf-exception-2.0",
        )
        for expression in expressions:
            errors = check_license.errors_for(expression)
            self.assertFalse(any("no operator between them" in error for error in errors), errors)


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

    def test_an_image_license_is_resolved_too(self):
        errors = []
        document = {"license": "MIT", "images": {"description": [{"id": "a", "license": "MTI"}]}}
        check_license.check_document("listings/Mod.toml", document, errors)
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("listings/Mod.toml: images.description[0].license: "))

    def test_an_image_without_a_license_adds_nothing(self):
        errors = []
        check_license.check_document("listings/Mod.toml", {"license": "MIT", "images": {"icon": {}}}, errors)
        self.assertEqual(errors, [])

    def test_a_valid_document_adds_nothing(self):
        errors = []
        check_license.check_document("listings/Mod.toml", {"license": "MIT"}, errors)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
