"""Spoken-text rules (tools/speech.py): US conventions only on US trips, units, respellings."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import speech as S


class Speak(unittest.TestCase):
    def test_us_roads(self):
        self.assertEqual(S.speak("Keep left onto I-64 West"), "Keep left onto I sixty-four West")
        self.assertEqual(S.speak("Turn right onto VA-234 (Dumfries Road)"), "Turn right onto Virginia two thirty-four, Dumfries Road")
        self.assertEqual(S.speak("near Hardy County, WV"), "Near Hardy County, West Virginia")

    def test_abroad_codes_are_not_us_states(self):     # the Setenil bug: CA-9113 read as "California ninety-one thirteen"
        self.assertEqual(S.speak("Turn left onto CA-9113", us=False), "Turn left onto C A ninety-one thirteen")
        self.assertEqual(S.speak("Join the A-357 at Cártama", us=False), "Join the A three fifty-seven at Cártama")
        self.assertEqual(S.speak("near Ronda, MA", us=False), "Near Ronda, MA")

    def test_words(self):
        self.assertEqual(S.words(832), "eight hundred thirty-two")
        self.assertEqual(S.words(31354), "thirty-one thousand three hundred fifty-four")
        self.assertEqual(S.route_num("9113"), "ninety-one thirteen")


class Units(unittest.TestCase):
    def test_auto(self):
        self.assertEqual(S.units_for("Woodbridge, Prince William County, Virginia, United States"), "mi")
        self.assertEqual(S.units_for("Bath, England, United Kingdom"), "mi")
        self.assertEqual(S.units_for("Setenil de las Bodegas, Cádiz, Andalucía, España"), "km")
        self.assertEqual(S.units_for(""), "mi")

    def test_km(self):
        u = S.Units("km")
        self.assertAlmostEqual(u(100), 160.9344)
        self.assertEqual((u.short, u.word, u.one), ("km", "kilometres", "kilometre"))


class Respell(unittest.TestCase):
    def test_longest_name_first_and_whole_words(self):
        lex = os.path.join(os.path.dirname(__file__), "_lex.json")
        open(lex, "w", encoding="utf-8").write('{"Setenil": "Seh-teh-neel", "Setenil de las Bodegas": "SDLB", "Niš": "Neesh"}')
        try:
            self.assertEqual(S.respell("to Setenil de las Bodegas via Niš", lex), "to SDLB via Neesh")
            self.assertEqual(S.respell("Setenilx stays", lex), "Setenilx stays")
        finally:
            os.remove(lex); S._LEX = None


if __name__ == "__main__":
    unittest.main()


class SaintAndSigns(unittest.TestCase):
    def test_saint_vs_street(self):
        self.assertEqual(S.speak("Keep right to stay on I-70 toward St Louis"), "Keep right to stay on I seventy toward Saint Louis")
        self.assertEqual(S.speak("Turn left onto Market St North"), "Turn left onto Market Street North")

    def test_bare_state_code_after_city(self):
        self.assertEqual(S.speak("Keep left onto I-470 West toward Columbus OH"), "Keep left onto I four seventy West toward Columbus, Ohio")
        self.assertEqual(S.speak("toward Columbus OH", us=False), "Toward Columbus OH")
