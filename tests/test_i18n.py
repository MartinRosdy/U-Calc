import unittest

from u_calc.i18n import CATALOGS, RU, translate, validate_catalogs


class I18nTests(unittest.TestCase):
    def test_ru_and_uz_catalogs_have_identical_keys(self) -> None:
        validate_catalogs()
        self.assertTrue(all(set(catalog) == set(RU) for catalog in CATALOGS.values()))

    def test_unknown_locale_falls_back_to_russian(self) -> None:
        self.assertEqual(translate("menu.new", "xx"), RU["menu.new"])

    def test_interpolation_works_in_both_languages(self) -> None:
        self.assertIn("Uy", translate("profiles.created", "uz", name="Uy"))
        self.assertIn("Дом", translate("profiles.created", "ru", name="Дом"))
