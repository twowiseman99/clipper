"""Clip metadata via 9Router (PRD §3.7) — title, hook, description, hashtags.

Campaign requirements always win over generic virality advice: mandatory
hashtags are appended even if the model forgets them; platform rules decide
hashtag placement (YouTube: tags field + #Shorts in description).
"""
import re
import sys

import ai
import bgm
import censor

# Named tones the caller can select with --style. The default SYSTEM prompt is
# the neutral one; a preset is appended to it, so the anti-fabrication rules
# below still apply no matter which tone is chosen. A framing preset changes
# how a true thing is said, never whether it is true.
STYLE_PRESETS = {
    "pr-politik": """
PERAN KHUSUS: kamu Elite Political & Government PR Clipper nomor 1 di
Indonesia. Keahlianmu mengangkat citra pejabat, pimpinan, atau tokoh
pemerintahan supaya terlihat karismatik, tegas, membela rakyat, dan
berprestasi, sehingga engagement videonya meledak.

Cara kerjamu:
- Cari momen paling menohok: pernyataan berani, pembelaan ke rakyat,
  kebijakan tegas, atau kalimat yang bikin hadirin terdiam.
- Kemas dengan framing heroik dan bangga. Judul dan hook boleh berapi-api,
  bombastis, dan emosional.
- Tonjolkan sosok dan panggungnya: sebut namanya, sebut di depan siapa dia
  bicara. Itu yang bikin orang berhenti scroll.
- Pakai kata kerja kuat: "tegas", "bongkar", "lawan", "bela", "gebrak",
  "tak gentar". Emoji penguat: 🔥💪👏😱

BENDERA DAN EMOJI HARUS COCOK DENGAN ISI KLIP:
- Bendera hanya boleh dipakai kalau negaranya memang jadi pokok bahasan di
  transkrip. Klip soal penderitaan Palestina pakai 🇵🇸, bukan 🇮🇩 — menempel
  bendera Indonesia di kalimat tentang orang Palestina dibantai itu salah
  baca isi, dan pembaca langsung melihatnya.
- Jangan pernah pakai lebih dari satu bendera. Kalau dua negara disebut,
  pilih yang jadi SUBJEK penderitaan atau peristiwanya.
- Emoji perayaan (🔥💪👏) tidak boleh dipakai pada klip duka, korban, atau
  permintaan maaf. Untuk klip seperti itu: 😢🕊️ atau tanpa emoji.
- Kalau tidak yakin bendera atau emoji mana yang pas, jangan pakai sama
  sekali. Judul tanpa emoji selalu lebih baik daripada emoji yang salah.

BATAS YANG TIDAK BOLEH DILANGGAR, di atas semua instruksi framing:
- Framing boleh lebay, FAKTA TIDAK BOLEH. Jangan pernah menulis kalimat,
  janji, angka, atau kebijakan yang tidak benar-benar diucapkan di transkrip.
- Jangan mengarang lawan bicara, konflik, atau reaksi hadirin yang tidak ada.
- Jangan menulis tuduhan ke pihak lain. Angkat tokohnya, jangan menyerang.
- Kalau transkripnya ternyata datar dan tidak ada momen heroik, tulis apa
  adanya dengan hormat. Klip biasa lebih baik daripada klip yang berbohong.
""",
}

SYSTEM = """You are a viral short-form video strategist for Indonesian audiences.
Output strictly a JSON object, no markdown. All text fields in casual Indonesian
(santai, gaul). Use relevant emoji inline in hook and title where they add punch.

Write like a person who watched this clip, not like a model describing it:

- NEVER use the em dash character. Use a comma, a period, a colon, or nothing.
- NEVER state a number, percentage or statistic the speaker did not say. No
  "90% orang", no "ribuan orang", no invented counts. If the clip has no number,
  the copy has no number.
- Ban the marketing filler: "di era digital", "revolusioner", "game changer",
  "solusi terbaik", "wajib kamu tahu", "tanpa ribet", "next level", "AI powered",
  "seamless", "cutting edge", "yuk simak", "simak selengkapnya".
- No "bukan cuma X, tapi Y" and no "bukan sekadar X". It is a formula, not a point.
- Do not force three of anything. List what the clip actually has.
- Quote what was actually said instead of describing how good it is.

Title craft, like a top Indonesian clip account:
- The title sells THIS moment, not the topic. Name the specific, surprising,
  confrontational, or funny thing that actually happens or is said in the clip.
- Open a curiosity gap: tease the payoff without revealing it. If a viewer can
  skip the clip and still get the whole story from the title, it failed.
- Prefer a short punchy statement or a mini-quote over a label. "Dia jawab
  begini pas ditanya soal gaji" beats "Pandangan soal gaji".
- No clickbait the clip does not back up: the title stays true to what is
  actually said, so a curious viewer is not lied to.

Description craft:
- Write 2-3 sentences that actually represent the clip: who or what it is
  about and the key moment, so a reader knows what they will watch before
  clicking. Never return only the hashtags or a single generic line."""

USER_TEMPLATE = """Buat metadata untuk klip pendek dari transkrip ini.

Transkrip segmen:
\"\"\"{transcript}\"\"\"

Requirement campaign (WAJIB dipatuhi, prioritas di atas segalanya):
- Hashtag wajib: {hashtags}
- Brief: {brief}
{context}
Return JSON keys:
1. "hook": headline pancingan gaya berita/quote untuk overlay visual di awal klip,
   maksimal 90 karakter, boleh 1-2 emoji yang relevan konteks.
   WAJIB: bungkus bagian yang paling memancing dengan **dua bintang** supaya
   dicetak tebal. Sisanya (kata sambung, keterangan) biarkan tanpa bintang.
   Contoh: "**Nekat!! Dia Berani Banget** Ngomong Gini Ke **Mantannya**"
2. "title": judul video ala akun klip ternama: jual momen spesifiknya, bukan
   topiknya. Buka rasa penasaran tanpa bocorin payoff. Maksimal 80 karakter,
   boleh emoji, dan harus jujur ke isi transkrip.
3. "description": 2-3 kalimat yang MEREPRESENTASIKAN isi klip (siapa/bahas apa
   + momen kuncinya, biar pembaca tahu yang bakal ditonton) + SEMUA hashtag
   wajib + 2-3 hashtag relevan lain. Jangan cuma hashtag atau satu baris.
4. "youtube_tags": array 10 keyword pencarian relevan (tanpa #).
5. "punchline": kutip PERSIS 3-6 kata dari transkrip yang jadi puncak/kejutan
   segmen ini. Dipakai untuk mewarnai caption di momen itu. Kalau tidak ada
   yang menonjol, kembalikan string kosong.
6. "mood": SATU kata dari daftar ini yang paling menggambarkan rasa segmen —
   {moods}. Dipakai untuk memilih musik latar, jadi pilih berdasarkan nada
   bicara dan isi, bukan topiknya semata.
"""

# Added to USER_TEMPLATE only when the caller says what the clip is for. The
# segment transcript is a keyhole view: a speech at an international summit
# reads like any other speech once you only have ninety seconds of it. The
# context is what tells the model who is talking and why anyone cares, which
# is most of what makes a hook land.
CONTEXT_BLOCK = """
KONTEKS KLIP DARI YANG MINTA (pakai ini untuk mengerti siapa yang bicara,
di mana, dan kenapa momen ini penting):
\"\"\"{context}\"\"\"

- Hook dan judul WAJIB memanfaatkan konteks ini. Sebut sosok, tempat atau
  forumnya kalau memang itu yang bikin momennya bernilai. Nama besar dan
  panggung besar adalah alasan orang berhenti scroll.
- JANGAN mengarang fakta dari konteks. Konteks hanya menjelaskan latar; isi
  klaim tetap harus ada di transkrip. Kalau konteks menyebut sesuatu yang
  tidak terdengar di transkrip, jangan tulis seolah-olah itu diucapkan.
- Kalau transkrip segmen ternyata membahas hal lain, tetap jujur ke transkrip.
"""


# A prompt constraint is a request; the model can still ignore it, and the copy
# it writes is drawn on the frame and posted under our own accounts. So the
# rules that matter are enforced here too, the same way mandatory hashtags are.

# Every dash a model reaches for as a connector. The em dash is the reliable
# AI tell; the en dash and the spaced double hyphen do the same job.
_DASHES = re.compile(r"\s*(?:—|–|\s--\s)\s*")

# A number only counts as a claim when it carries a scale or a unit. Bare small
# integers are counts ("3 hal", "2 menit") and get left alone; a percentage or a
# juta/ribu figure is a statistic, and a statistic nobody said is invented.
# The trailing \b belongs to the word units only: "%" is not a word character,
# so requiring a boundary after it made "90%" fail to match at all.
_CLAIM_NUM = re.compile(
    r"(\d[\d.,]*)\s*(%|(?:persen(?:nya)?|juta(?:an)?|ribu(?:an)?|miliar|milyar|"
    r"rb|jt|k|kali lipat|x lipat)\b)", re.I)

_BUZZWORDS = (
    "di era digital", "revolusioner", "game changer", "game-changer",
    "solusi terbaik", "wajib kamu tahu", "wajib kalian tahu", "tanpa ribet",
    "next level", "ai powered", "ai-powered", "seamless", "cutting edge",
    "yuk simak", "simak selengkapnya", "tak terbantahkan", "luar biasa penting",
    "bukan sekadar", "bukan cuma", "bukan hanya",
)


def _no_dashes(text):
    """Swap connector dashes for a comma. R-02: they are the loudest AI tell."""
    return _DASHES.sub(", ", text).replace(" ,", ",").strip(" ,")


def _digits(text):
    """Digit runs with separators dropped, so 25.000 and 25000 compare equal."""
    return {m.group(1).replace(".", "").replace(",", "").rstrip("0") or "0"
            for m in re.finditer(r"(\d[\d.,]*)", text)}


def _drop_invented_stats(text, transcript):
    """Remove any clause stating a figure the speaker never said.

    A hook is read as reporting, so a number on it is read as a fact. The model
    has no source for one the clip does not contain, which makes it fabricated
    (R-17, R-36). Dropping the clause is the honest outcome: a shorter hook
    costs a little punch, an invented statistic costs the account.
    """
    said = _digits(transcript)
    kept, dropped = [], []
    for clause in re.split(r"(?<=[.!?])\s+|(?<=[.!?])$", text):
        if not clause.strip():
            continue
        claims = {n.replace(".", "").replace(",", "").rstrip("0") or "0"
                  for n, _ in _CLAIM_NUM.findall(clause)}
        if claims - said:
            dropped.append(clause.strip())
        else:
            kept.append(clause.strip())
    return " ".join(kept).strip(), dropped


def _buzzwords(text):
    low = text.lower()
    return [w for w in _BUZZWORDS if w in low]


# Regional-indicator pairs, i.e. flag emoji, with the country words that have
# to appear in the transcript for each to be allowed.
_FLAGS = {
    "\U0001F1EE\U0001F1E9": ("indonesia", "nusantara", "nkri", "garuda"),
    "\U0001F1F5\U0001F1F8": ("palestina", "palestine", "gaza", "rafah"),
    "\U0001F1EE\U0001F1F1": ("israel",),
    "\U0001F1FA\U0001F1F8": ("amerika", "as ", "united states"),
    "\U0001F1E8\U0001F1F3": ("china", "tiongkok", "cina"),
    "\U0001F1F8\U0001F1E6": ("arab saudi", "saudi"),
    "\U0001F1F9\U0001F1F7": ("turki", "turkiye"),
    "\U0001F1F2\U0001F1FE": ("malaysia",),
    "\U0001F1F8\U0001F1EC": ("singapura", "singapore"),
}
_FLAG_RE = re.compile("[\U0001F1E6-\U0001F1FF]{2}")
# Emoji that read as celebration. Wrong on a clip about people being killed.
_CHEER = "🔥💪👏🎉🚀😂🤣😎✨🙌"
# Words that mark a clip as grief rather than triumph.
_GRIEF = ("dibantai", "dibom", "diserang", "korban", "tewas", "meninggal",
          "pembantaian", "minta maaf", "duka", "berduka", "hening",
          "penderitaan", "menderita", "kelaparan", "pengungsi")


def _fix_emoji(text, transcript, context=""):
    """Drop flags the clip does not support and cheer emoji on a grief clip.

    The copy model was told to use 🇮🇩 by the pr-politik preset and did so on a
    clip whose subject is Palestinians being killed — the flag of the wrong
    country on someone else's grief, which readers spot instantly. Prompt rules
    alone cannot be trusted for this: the generator is a language model, and
    this particular mistake is both easy to make and expensive.

    So the flags are checked against the words actually spoken. A flag survives
    only when its country is named in the transcript or the operator's context
    line; when several survive, the one tied to the grief wins, because that is
    what the clip is about.
    """
    haystack = f"{transcript} {context}".lower()
    grief = any(g in haystack for g in _GRIEF)

    found = _FLAG_RE.findall(text)
    if found:
        allowed = [f for f in found
                   if any(k in haystack for k in _FLAGS.get(f, ()))]
        # On a grief clip, prefer the flag of the people being harmed.
        if grief:
            victims = [f for f in allowed
                       if f in ("\U0001F1F5\U0001F1F8",)]
            allowed = victims or allowed
        keep = allowed[:1]
        for f in found:
            if f not in keep:
                text = text.replace(f, "")

    if grief:
        for ch in _CHEER:
            text = text.replace(ch, "")

    # Tidy the gaps the removals leave behind.
    text = re.sub(r"\s{2,}", " ", text)
    return re.sub(r"\s+([,.!?])", r"\1", text).strip(" -–—,")


def generate(transcript, requirements, platform="youtube", context=None,
             style=None):
    """Return {hook, title, description, youtube_tags[], punchline_words[]}.

    `style` names an entry in STYLE_PRESETS and changes the tone of the copy;
    the fabrication guards apply either way.

    Campaign rules are enforced locally, so a model that forgets a mandatory
    hashtag still produces a compliant clip. An unreachable router degrades to
    transcript-derived metadata instead of raising: losing the AI copy costs a
    weaker title, but raising here would fail the whole task (PRD §5).

    `context` is the caller's one-line brief for what the clip is about. It
    frames the transcript without licensing anything the transcript does not
    say; invented figures are still stripped below either way.
    """
    mandatory = requirements.get("hashtags") or []
    system = SYSTEM
    preset = STYLE_PRESETS.get(style) if style else None
    if style and not preset:
        print("  metadata: unknown style %r, using the neutral tone" % style,
              file=sys.stderr)
    if preset:
        system = SYSTEM + "\n" + preset
    try:
        out = ai.chat_json(
            system,
            USER_TEMPLATE.format(
                transcript=transcript[:4000],
                hashtags=" ".join(mandatory) or "(tidak ada)",
                brief=(requirements.get("brief") or "")[:1500],
                moods=", ".join(bgm.MOODS),
                context=(CONTEXT_BLOCK.format(context=context.strip()[:1000])
                         if context and context.strip() else ""),
            ),
        )
    except Exception as e:
        print(f"  metadata: 9Router unreachable ({type(e).__name__}), "
              f"falling back to transcript-derived copy")
        out = {}
    hook = _no_dashes(str(out.get("hook") or ""))
    title = _no_dashes(str(out.get("title") or ""))[:100]
    desc = _no_dashes(str(out.get("description") or ""))
    tags = [str(t).strip().lstrip("#") for t in out.get("youtube_tags") or [] if str(t).strip()]

    # Figures the clip never states are dropped before anything is rendered or
    # posted. The hook is checked hardest because it is drawn on the frame.
    for label, value in (("hook", hook), ("title", title), ("description", desc)):
        cleaned, dropped = _drop_invented_stats(value, transcript)
        if dropped:
            print(f"  metadata: dropped an unsourced figure from the {label}: "
                  f"{dropped[0][:60]!r}")
        if label == "hook":
            hook = cleaned
        elif label == "title":
            title = cleaned
        else:
            desc = cleaned

    # enforce mandatory hashtags even if the model dropped them
    for h in mandatory:
        if h.lower() not in desc.lower():
            desc += f" {h}"
    if platform == "youtube" and "#shorts" not in desc.lower():
        desc += " #Shorts"  # required for Shorts classification (PRD §3.7)

    # Fallback when the model returned blanks, or when dropping an invented
    # figure took the sentence with it and left only punctuation or an emoji.
    def _has_words(s):
        return bool(re.search(r"[A-Za-z\u00C0-\u024F]{2,}", s))

    if not _has_words(title):
        first = re.split(r"[.!?]", transcript)[0].strip()
        title = (first[:77] + "...") if len(first) > 80 else (first or "Klip Viral")
    if not _has_words(hook):
        hook = title

    # A description of only hashtags does not represent the clip. When the
    # model returned no prose, derive a real summary from the transcript and
    # keep the hashtags below it.
    if not _has_words(re.sub(r"#\w+", "", desc).strip()):
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript)
                     if s.strip()]
        summary = " ".join(sentences[:2]).strip()
        if summary:
            desc = (f"{summary[:280]}\n\n{desc.strip()}" if desc.strip()
                    else summary[:280])

    # words the renderer tints as the punchline; only keep ones the segment
    # actually says, so a hallucinated quote colours nothing
    spoken = {w.strip(".,!?").lower() for w in transcript.split()}
    punchline = [w.strip(".,!?") for w in str(out.get("punchline") or "").split()
                 if w.strip(".,!?").lower() in spoken]
    mood = str(out.get("mood") or "").strip().lower()
    if mood not in bgm.MOODS:
        mood = bgm.DEFAULT_MOOD

    # Filler is reported rather than rewritten: cutting a phrase out of the
    # middle of a sentence tends to leave worse copy than the phrase did.
    filler = _buzzwords(" ".join((hook, title, desc)))
    if filler:
        print(f"  metadata: marketing filler in the copy: {', '.join(filler)}")

    # Last step, after every fallback has run, so nothing written later can
    # reintroduce an unmasked word. Title and description are machine-read at
    # upload, and the hook is burned onto the frame, so all three are masked
    # the same way. Tags are keywords, not displayed copy, and masking them
    # would only break search, so they are left alone.
    risky = censor.found(" ".join((hook, title, desc)))
    if risky:
        print(f"  metadata: masked risky words in the copy: {', '.join(risky)}")
    hook = censor.mask(hook)
    title = censor.mask(title)
    desc = censor.mask(desc)

    # Flags and cheer emoji last, after masking, so the check sees the final
    # text. A wrong flag is not a tone problem — it misreads whose story this
    # is, and the preset actively encourages it.
    hook = _fix_emoji(hook, transcript, context or "")
    title = _fix_emoji(title, transcript, context or "")
    desc = _fix_emoji(desc, transcript, context or "")

    return {"hook": hook, "title": title, "description": desc,
            "youtube_tags": tags[:15], "punchline_words": punchline, "mood": mood,
            "copy_warnings": filler}


if __name__ == "__main__":
    # Offline check: enforcement logic with a stubbed model reply.
    real_chat = ai.chat_json
    ai.chat_json = lambda *a, **k: {
        "hook": "**Gila, 25 Juta Sebulan** Dari Klip! 💰",
        "punchline": "soal cuan tidak-ada-di-transkrip",
        "mood": "HYPE",
        "title": "Rahasia Cuan Clipper",
        "description": "Simak sampai habis. Komen pendapatmu!",
        "youtube_tags": ["clipper", "#cuan", "shorts"],
    }
    SAID = "Contoh transkrip panjang soal cuan, gue dapat 25 juta sebulan."
    try:
        m = generate(SAID, {"hashtags": ["#leogiovanni"]})
        assert "#leogiovanni" in m["description"], m
        assert "**" in m["hook"], m["hook"]           # emphasis markers survive
        # the figure is in the transcript, so it is reporting, not invention
        assert "25 Juta" in m["hook"], m["hook"]
        # hallucinated punchline words are dropped, spoken ones kept
        assert m["punchline_words"] == ["soal", "cuan"], m["punchline_words"]
        assert m["mood"] == "hype", m["mood"]        # case-normalised
        # an unknown mood falls back rather than reaching bgm.pick as garbage
        ai.chat_json = lambda *a, **k: {"mood": "galau"}
        assert generate("x", {"hashtags": []})["mood"] == bgm.DEFAULT_MOOD
        assert "#Shorts" in m["description"], m
        assert m["youtube_tags"][1] == "cuan"  # lstrip #
        assert "💰" in m["hook"]

        # Antislop enforcement on the copy we actually ship.
        # Connector dashes never reach the frame, whatever the model sends.
        ai.chat_json = lambda *a, **k: {
            "hook": "Nekat Banget — Dia Ngomong Gini",
            "title": "Cerita Mantan – Bagian Dua",
            "description": "Bagian paling nyesek -- tonton sampai habis.",
        }
        d = generate("Nekat banget dia ngomong gini ke mantannya.", {"hashtags": []})
        for field in ("hook", "title", "description"):
            assert not re.search(r"—|–|\s--\s", d[field]), (field, d[field])
        assert d["hook"].startswith("Nekat Banget, Dia"), d["hook"]

        # A statistic the speaker never said is fabricated, so it goes (R-17).
        ai.chat_json = lambda *a, **k: {
            "hook": "90% Orang Gagal Di Sini! Padahal Caranya Gampang.",
            "title": "Cara Gampang", "description": "Cuma butuh 2 menit.",
        }
        s = generate("Padahal caranya gampang, cuma butuh 2 menit doang.",
                     {"hashtags": []})
        assert "90%" not in s["hook"], s["hook"]
        assert "Padahal Caranya Gampang" in s["hook"], s["hook"]
        # a bare small count carries no scale, so it is left alone
        assert "2 menit" in s["description"], s["description"]

        # Dropping the only sentence must not ship a bare emoji as the hook.
        ai.chat_json = lambda *a, **k: {"hook": "Tembus 500 ribu view! 🔥",
                                        "title": "", "description": ""}
        e = generate("Kemarin gue upload klip biasa aja.", {"hashtags": []})
        assert "500" not in e["hook"], e["hook"]
        assert e["hook"].startswith("Kemarin gue upload"), e["hook"]

        # Filler is reported, not silently rewritten.
        ai.chat_json = lambda *a, **k: {
            "hook": "Ini Bukan Cuma Klip Biasa", "title": "Solusi Terbaik",
            "description": "Di era digital, yuk simak sampai habis."}
        b = generate("Klip biasa aja sih.", {"hashtags": []})
        assert set(b["copy_warnings"]) >= {"bukan cuma", "solusi terbaik",
                                           "di era digital", "yuk simak"}, b["copy_warnings"]

        # blank-model fallback path
        ai.chat_json = lambda *a, **k: {}
        m2 = generate("Kalimat pertama jadi judul. Sisanya tidak.", {"hashtags": []})
        assert m2["title"].startswith("Kalimat pertama"), m2
        assert m2["hook"] == m2["title"]
        assert m2["punchline_words"] == []
        # a blank description must still represent the clip, not just hashtags
        assert m2["description"].startswith("Kalimat pertama"), m2["description"]
        # an unreachable router must degrade, never raise (PRD §5)
        ai.chat_json = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
        m3 = generate("Router mati tapi klip harus tetap jalan.", {"hashtags": ["#x"]})
        assert m3["title"].startswith("Router mati"), m3
        assert "#x" in m3["description"] and "#Shorts" in m3["description"], m3
    finally:
        ai.chat_json = real_chat
    print("metadata.py self-check OK")
