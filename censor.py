"""Mask the words that get a clip taken down, without changing what it says.

Short-form platforms moderate on text far harder than on speech: burned-in
captions, the title and the description are machine-read on upload, while the
audio usually is not. A clip about a massacre is not the problem; the word
"dibantai" sitting on the frame in 90pt type is. Clipper accounts work around
this by starring a letter out, which keeps the meaning legible to a human and
takes the exact string out of a keyword match.

Only the letter is hidden. Nothing is removed, softened, or reworded, so the
caption still matches what the speaker actually said.

    >>> mask("mereka DIBANTAI terus")
    'mereka DIB*NTAI terus'

The list covers violence, death, drugs and slurs — the categories that carry
takedown and demonetisation risk on TikTok, Reels and Shorts. It is deliberately
short: every entry costs readability, so a word earns its place by actually
being risky, not by being unpleasant.
"""
import re

# Stems, not whole words: Indonesian inflects heavily (bunuh, membunuh,
# dibunuh, pembunuhan) and a list of full forms would miss most of them. The
# index is where the star goes, counted from the start of the stem — a vowel,
# so the word stays pronounceable in the head.
_STEMS = (
    # --- violence, Indonesian ---
    ("bantai", 4),       # bant*i
    ("bunuh", 3),        # bun*h
    ("tembak", 4),       # temb*k
    ("nembak", 4),       # meN- eats the t: menembak, penembakan
    ("mbunuh", 4),       # meN- doubles the m: membunuh
    ("perkosa", 4),      # perk*sa
    ("merkosa", 4),      # memperkosa
    ("bacok", 3),        # bac*k
    ("mutilasi", 4),     # muti*asi
    ("genosida", 4),     # geno*ida
    ("teroris", 3),      # ter*ris
    ("bom", 1),          # b*m
    # Attack words, which a political clip leans on constantly. Two entries
    # because meN-/peN- turn the s into ny (serang -> menyerang), so the bare
    # stem is no longer in the word to find. "serangga" and "serangkaian" do
    # not match: the closed suffix list means a stem must end the word.
    ("serang", 3),       # ser*ng, diserang, serangan
    ("nyerang", 4),      # menyerang, penyerangan
    ("ledak", 3),        # led*k
    ("sadis", 3),
    ("siksa", 3),
    ("culik", 3),
    ("mayat", 1),        # m*yat
    ("jenazah", 3),
    # --- violence, English ---
    ("kill", 2),         # ki*l
    ("killed", 2),
    ("killing", 2),
    ("murder", 3),       # mur*er
    ("massacre", 4),     # mass*cre
    ("genocide", 4),
    ("shoot", 3),
    ("shooting", 3),
    ("stab", 2),
    ("rape", 2),         # r*pe
    ("torture", 3),
    ("terrorist", 3),
    ("bomb", 1),         # b*mb
    ("attack", 3),
    ("violence", 3),
    ("blood", 3),
    ("gore", 2),
    ("corpse", 3),
    ("dead body", 2),
    ("execution", 4),
    ("behead", 3),
    ("slaughter", 4),
    ("abuse", 2),
    ("assault", 4),
    # --- self-harm: the hardest category on every platform ---
    ("bunuh diri", 3),
    ("gantung diri", 4),
    ("suicide", 2),      # su*cide
    ("self harm", 5),
    ("self-harm", 5),
    ("kys", 1),
    ("depresi", 4),
    ("overdosis", 5),
    ("overdose", 5),
    # --- drugs ---
    ("narkoba", 4),      # nark*ba
    ("sabu", 1),
    ("ganja", 1),
    ("kokain", 3),
    ("cocaine", 3),
    ("heroin", 3),
    ("meth", 2),
    ("weed", 2),
    ("drugs", 2),
    ("mabuk", 3),
    # --- sexual ---
    ("porno", 3),
    ("bokep", 3),
    ("telanjang", 4),
    ("mesum", 3),
    ("pelakor", 4),
    ("nude", 2),
    ("naked", 2),
    ("sex", 1),          # s*x
    ("sexual", 1),
    ("onlyfans", 4),
    ("escort", 3),
    ("prostitusi", 5),
    ("prostitute", 5),
    # --- genitals / body, Indonesian: the words a caption cannot show ---
    ("kelamin", 3),      # kel*min
    ("kemaluan", 3),     # kem*luan
    ("penis", 2),        # pe*is
    ("vagina", 3),       # vag*na
    ("titit", 3),
    ("peler", 3),
    ("itil", 2),
    ("pepek", 3),
    ("toket", 3),
    ("tetek", 3),
    ("jembut", 3),
    ("pantat", 3),
    ("sperma", 3),
    ("coli", 2),
    ("onani", 3),
    ("masturbasi", 4),
    ("ngewe", 3),
    ("sange", 3),
    ("crot", 2),
    # --- genitals / body, English ---
    ("dick", 2),
    ("cock", 2),
    ("pussy", 3),
    ("boobs", 2),
    ("tits", 2),
    ("horny", 3),
    # --- slurs / profanity that trips filters ---
    ("anjing", 1),
    ("bangsat", 4),
    ("kontol", 3),
    ("memek", 2),
    ("ngentot", 4),
    ("ngentod", 4),
    ("jancok", 3),
    ("pukimak", 4),
    ("kampang", 4),
    ("bajingan", 3),
    ("goblok", 3),
    ("tolol", 3),
    ("bego", 2),
    ("idiot", 2),
    ("kampret", 4),
    ("keparat", 4),
    ("brengsek", 4),
    ("bacot", 2),
    ("laknat", 3),
    ("bangke", 3),
    ("taik", 2),
    ("asu", 1),
    ("fuck", 2),         # fu*k
    ("shit", 2),
    ("bitch", 2),
    ("bastard", 3),
    ("nigga", 2),
    ("retard", 3),
    ("whore", 2),
    ("slut", 2),
    # --- scam / financial, demonetisation bait ---
    ("penipuan", 4),
    ("scam", 2),
    ("judi", 1),
    ("gambling", 4),
    ("slot gacor", 5),
)

# Longest first, so "bunuh diri" masks as a phrase before "bunuh" claims it.
_STEMS = tuple(sorted(_STEMS, key=lambda s: -len(s[0])))

# Indonesian builds on stems with prefixes, and a prefix can change the stem's
# first letter: meN- turns tembak into menembak and bunuh into membunuh, so the
# bare stem is no longer there to find. Each entry therefore also carries its
# nasalised form where one exists.
_PREFIX = r"(?:di|me|mem|men|meng|menge|pe|pem|pen|peng|penge|ter|ber|ke|keter|per|se)?"

# A closed set of suffixes on the end, for the same reason in reverse: a stem
# may carry -an/-nya/-kan or an English -s/-ed/-ing, but nothing else. Without
# this "gore" fires inside "gorengan" and "sabu" inside "kesabuan".
_SUFFIX = r"(?:an|nya|kan|ku|mu|lah|kah|es|s|ed|ing)?\b"

# Stems that only ever appear with a prefix attached must not fire bare — "sabu"
# inside "kesabu" is a coincidence, while "dibantai" is not. These require a
# real word boundary on both sides, no prefix allowed.
#
# "bom" was in this set and so "dibom" shipped unmasked in a clip about Gaza,
# which is exactly the word that needed masking. It is safe to allow prefixes:
# the closed suffix list means "bombardir", "bomber" and "bombai" still do not
# match, because none of them end at the stem.
_STRICT = {"sabu", "mati", "sex", "gore", "meth", "weed", "kys"}

_COMPILED = tuple(
    (re.compile(r"\b" + ("" if stem in _STRICT else _PREFIX)
                + "(" + re.escape(stem).replace(r"\ ", r"\s+") + ")"
                + _SUFFIX, re.IGNORECASE), idx)
    for stem, idx in _STEMS)


def _star(match_text, idx):
    """Replace one character of `match_text` with '*', preserving the rest."""
    if idx >= len(match_text):
        idx = len(match_text) // 2
    return match_text[:idx] + "*" + match_text[idx + 1:]


def mask(text):
    """Star out one letter of every risky stem found in `text`.

    Case and surrounding characters are left alone, so an upper-case caption
    comes back upper-case and a prefix like "di" or a suffix like "-an"
    survives intact. Returns the text unchanged when it contains nothing on
    the list.
    """
    if not text:
        return text

    def sub(m, idx):
        # rebuild the whole match, replacing only the stem group inside it:
        # the prefix and suffix the pattern matched have to come back too
        lo = m.start(1) - m.start(0)
        hi = m.end(1) - m.start(0)
        whole = m.group(0)
        return whole[:lo] + _star(m.group(1), idx) + whole[hi:]

    for pattern, idx in _COMPILED:
        text = pattern.sub(lambda m, i=idx: sub(m, i), text)
    return text


def found(text):
    """The risky stems present in `text`, for logging what was masked."""
    if not text:
        return []
    return [stem for (pattern, _idx), (stem, _i) in zip(_COMPILED, _STEMS)
            if pattern.search(text)]


def _selfcheck():
    # masks what it should
    assert mask("mereka DIBANTAI terus") == "mereka DIBANT*I terus", mask("mereka DIBANTAI terus")
    assert mask("dia dibunuh kemarin") == "dia dibun*h kemarin", mask("dia dibunuh kemarin")
    assert mask("pembunuhan itu") == "pembun*han itu", mask("pembunuhan itu")
    assert mask("mereka di bom") == "mereka di b*m", mask("mereka di bom")
    assert mask("he was killed") == "he was ki*led", mask("he was killed")
    assert mask("a MASSACRE happened") == "a MASS*CRE happened", mask("a MASSACRE happened")
    assert mask("suicide rates") == "su*cide rates", mask("suicide rates")
    assert mask("what the fuck") == "what the fu*k", mask("what the fuck")
    # genitals and crude words: the ones a burned-in caption cannot show
    assert mask("alat KELAMIN") == "alat KEL*MIN", mask("alat KELAMIN")
    assert mask("dasar kontol") == "dasar kon*ol", mask("dasar kontol")
    assert mask("anjing lu bego") == "a*jing lu be*o", mask("anjing lu bego")
    # nasalised prefixes: the stem's own first letter is gone
    assert mask("dia menembak") == "dia menemb*k", mask("dia menembak")
    assert mask("penembakan itu") == "penemb*kan itu", mask("penembakan itu")
    assert mask("dia membunuh") == "dia membun*h", mask("dia membunuh")

    # leaves innocent words alone — the expensive failure, since a false
    # positive puts a star in ordinary copy where a viewer sees a typo
    for clean in ("kombomba", "gorengan", "seksi", "matikan lampu",
                  "router mati", "dia mati lampu", "kesabu", "kesabuan",
                  "administrasi", "kesabaran", "stabil", "bomber jacket",
                  "bombastis", "kombinasi", "berjudul", "judul", "ganjil",
                  "pengadilan", "pendidikan", "sabun", "sabar", "keju",
                  "pantai", "pantas", "pantau", "koleksi", "kolega", "colek",
                  "asuransi", "asuhan", "asumsi", "mengasuh", "tasik",
                  "digital", "kapital", "titik", "kampung", "kampus",
                  "identitas", "ideologi", "membaca", "sangat", "sangka",
                  "sanggup", "tiket", "cocok", "cokelat", "dokter",
                  "bolos", "bola", "horor", "horizon", "policy",
                  # Added with the attack stems: "serang" must not fire inside
                  # an insect or a series, and allowing prefixes on "bom" must
                  # not reach "bombardir".
                  "serangga", "serangkaian", "bombardir", "seruan", "seram",
                  "berseru", "serangga di taman"):
        got = mask(clean)
        assert got == clean, f"false positive: {clean!r} -> {got!r}"

    # The words this clip actually says. "dibom" and "diserang" shipped
    # unmasked once, so they are asserted rather than assumed.
    for word, want in (("dibom", "dib*m"), ("diserang", "diser*ng"),
                       ("menyerang", "menyer*ng"), ("serangan", "ser*ngan"),
                       ("penyerangan", "penyer*ngan"),
                       ("dibantai", "dibant*i")):
        assert mask(word) == want, (word, mask(word))

    assert mask("") == ""
    assert mask(None) is None
    assert found("mereka DIBANTAI") == ["bantai"], found("mereka DIBANTAI")
    print("censor.py self-check OK")
    for s in ("dibantai", "dibunuh", "ditembak", "narkoba", "anjing",
              "pembantaian", "DIBANTAI", "di bom", "killed", "massacre",
              "suicide", "fuck"):
        print(f"  {s} -> {mask(s)}")


if __name__ == "__main__":
    _selfcheck()
