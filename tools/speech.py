"""Turning route text into words a TTS voice reads well: numbers, highway numbers, US state codes, units and
hard place names. Pure functions, no I/O except loading the respelling list, so they are unit-tested
(tests/test_speech.py) and shared by routevid3.py and worldtrip.py.

US conventions (I-64 "I sixty-four", VA-234 "Virginia two thirty-four", ", MO" "Missouri") apply only when
us=True: abroad, CA-9113 is a Spanish road ("C A ninety-one thirteen"), not California.
"""
import json, os, re

US_ABBR = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO", "Connecticut": "CT",
           "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
           "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
           "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
           "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
           "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
           "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
           "District of Columbia": "DC"}
ABBR_US = {v: k for k, v in US_ABBR.items()}
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
KM_PER_MI = 1.609344


def words(n):
    """An integer in words: 832 -> 'eight hundred thirty-two', 19483 -> 'nineteen thousand four hundred eighty-three'."""
    n = int(round(n))
    if n < 0: return "minus " + words(-n)
    if n < 20: return ONES[n]
    if n < 100: return TENS[n // 10] + ("" if n % 10 == 0 else "-" + ONES[n % 10])
    if n < 1000: return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + words(n % 100))
    if n < 1_000_000: return words(n // 1000) + " thousand" + ("" if n % 1000 == 0 else " " + words(n % 1000))
    return words(n // 1_000_000) + " million" + ("" if n % 1_000_000 == 0 else " " + words(n % 1_000_000))


def route_num(s):
    """Highway numbers the way people say them: 64 -> sixty-four, 264 -> two sixty-four, 508 -> five oh eight, 9113 -> ninety-one thirteen."""
    n = int(re.match(r"\d+", s).group()); suffix = s[len(str(n)):]
    if n < 100: out = words(n)
    elif n < 1000: out = ONES[n // 100] + " " + ("oh " + ONES[n % 100] if 0 < n % 100 < 10 else ("hundred" if n % 100 == 0 else words(n % 100)))
    elif n < 10000: out = words(n // 100) + " " + ("hundred" if n % 100 == 0 else ("oh " + ONES[n % 100] if n % 100 < 10 else words(n % 100)))
    else: out = words(n)
    return out + (" " + " ".join(suffix) if suffix else "")


def speak(text, us=True):
    """Card text -> spoken text. Abroad (us=False) road prefixes are read letter by letter and ', XX' is left alone."""
    t = text.replace("&", "and").replace("·", ",")
    t = re.sub(r"\(([^)]*)\)", r", \1,", t)
    def ref(m):
        pre, num = m.group(1), m.group(2)
        if us:
            if pre == "I": return f"I {route_num(num)}"
            if pre == "US": return f"U.S. {route_num(num)}"
            if pre == "SR": return f"state route {route_num(num)}"
            if pre == "CR": return f"county road {route_num(num)}"
            if pre in ABBR_US: return f"{ABBR_US[pre]} {route_num(num)}"
        return f"{' '.join(pre) if len(pre) > 1 else pre} {route_num(num)}"
    t = re.sub(r"\b([A-Z]{1,3})-(\d+[A-Z]?)\b", ref, t)
    t = re.sub(r"\bAlt\b\.?", "alternate", t); t = re.sub(r"\bBus\.", "business", t)
    if us: t = re.sub(r",\s*([A-Z]{2})\b", lambda m: ", " + ABBR_US.get(m.group(1), m.group(1)), t)
    # "St": Saint before a place name after a lowercase word ("toward St Louis"), else Street ("Market St North")
    def _st(m):
        before = t[:m.start()].rstrip(); prev = before.split()[-1] if before.split() else ""
        return "Saint " if not prev or prev[-1] in ",:" or prev.islower() else m.group(0)
    t = re.sub(r"\bSt\.? (?=[A-Z][a-z])", _st, t)
    if us:   # a bare state code after a place on a sign: "toward Columbus OH" -> "Columbus, Ohio"
        t = re.sub(r"\b([A-Z][a-z]+) ([A-Z]{2})\b(?!-)", lambda m: f"{m.group(1)}, {ABBR_US[m.group(2)]}" if m.group(2) in ABBR_US else m.group(0), t)
    for a, b in (("Va Beach", "Virginia Beach"), (" St ", " Street "), (" Ave ", " Avenue "), (" Blvd", " Boulevard"), (" Hwy", " Highway"), (" Pkwy", " Parkway")):
        t = t.replace(a, b)
    t = re.sub(r"\b(\d+)\b", lambda m: words(int(m.group(1))), t)
    t = re.sub(r"\s+,", ",", re.sub(r",\s*,", ",", re.sub(r"\s+", " ", t))).strip(" ,")
    return t[0].upper() + t[1:] if t else t


def hm_words(sec):
    h, m = divmod(int(round(sec / 60)), 60)
    if h and m: return f"{words(h)} hour{'s' if h > 1 else ''} {words(m)} minutes"
    return f"{words(h)} hour{'s' if h > 1 else ''}" if h else f"{words(m)} minutes"


class Units:
    """Distances are kept in miles inside the tools; this only changes what is shown and said."""
    def __init__(self, kind="mi"):
        self.km = kind == "km"; self.f = KM_PER_MI if self.km else 1.0
        self.short, self.word, self.one = ("km", "kilometres", "kilometre") if self.km else ("mi", "miles", "mile")
    def __call__(self, miles): return miles * self.f


def units_for(country_or_display):
    """'auto' units from the start's country: miles in the US and the UK, kilometres elsewhere."""
    s = (country_or_display or "").strip()
    return "mi" if not s or re.search(r"(United States|United Kingdom|USA|\bUK\b)\s*$", s) else "km"


_LEX = None
def respell(text, lexicon_path=None):
    """Spoken text only (subtitles keep the real spelling): swap hard place names for phonetic respellings
    from data/pronounce.json, e.g. Ljubljana -> 'Lyoo-blyah-nah'."""
    global _LEX
    if _LEX is None or lexicon_path:
        p = lexicon_path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pronounce.json")
        _LEX = {k: v for k, v in (json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}).items() if not k.startswith("_")}
    for name in sorted(_LEX, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", _LEX[name], text)
    return text
