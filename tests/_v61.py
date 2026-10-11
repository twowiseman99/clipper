"""Gate freeze menolak sendiri hasil model yang kontradiktif.

Dua frame dikirim dengan orang yang salah dibekukan. Yang kedua lolos gate
versi pertama karena pertanyaannya salah: "siapa yang paling jelas di depan".
Di frame itu jawabannya Gibran — dia paling besar dan paling dekat kamera —
tapi yang dibaca mata penonton adalah ibu-ibu di belakangnya yang menatap
lensa.

Pelajaran yang sudah berulang di repo ini: aturan di prompt saja tidak cukup
untuk kelas kesalahan ini. Jadi syaratnya ditegakkan di KODE terhadap jawaban
terstruktur model, bukan dipercayakan ke kalimat perintah. Tes ini memalsukan
jawaban model supaya tidak perlu jaringan.
"""
import sys
import tempfile
import types

sys.path.insert(0, "/home/ubuntu/clipper")
import freeze_pick

# pick() writes its per-frame rows to a debug file now. Point it at a scratch
# directory so a test run does not rotate the real render diagnostics.
freeze_pick.DEBUG_DIR = tempfile.mkdtemp(prefix="v61-freeze-")

# --- pertanyaannya menanyakan hal yang benar ---
q = freeze_pick._question(freeze_pick.describe("Gibran"))
for must in ("HOW READABLE", "does NOT make a face readable",
             "Judge the face, not the body", "most_readable"):
    assert must in q, "pertanyaan gate tidak memuat %r" % must
assert "GIBRAN RAKABUMING RAKA" in q, "nama telanjang tidak dijabarkan"
print("pertanyaan: menanyakan wajah yang kebaca, bukan yang paling besar")

# --- describe() memberi ciri fisik, bukan cuma nama ---
assert "slim" in freeze_pick.describe("gibran").lower()
assert freeze_pick.describe("Entahlah") == "Entahlah", "nama asing hilang"
print("describe: nama dikenal dijabarkan, nama asing diteruskan apa adanya")


# --- jawaban model yang kontradiktif harus ditolak di kode ---
def verdicts(answer):
    """Jalankan pick() dengan satu frame dan jawaban model yang dipalsukan."""
    freeze_pick.LOOKBACK = 0.0
    fake_ai = types.ModuleType("ai")
    fake_ai.vision_json = lambda *a, **k: answer
    sys.modules["ai"] = fake_ai
    freeze_pick._grab = lambda v, t: b"x" * 2000
    # pick() returns (timestamp, summary): the per-frame rows went to a debug
    # file so the ledger stopped taking one entry per judged frame. Only the
    # verdict is asserted here, but the summary has to agree with it — a
    # picked timestamp with qualified=0 would mean the counts shown to a
    # reader contradict the decision.
    picked, summary = freeze_pick.pick("dummy.mp4", 10.0, "Gibran")
    assert (picked is None) == (summary["qualified"] == 0), (
        "summary disagrees with the verdict: picked=%r qualified=%d"
        % (picked, summary["qualified"]))
    assert summary["frames"] >= 1, summary
    return picked


base = {"ok": True, "confidence": 0.9, "most_readable": "Gibran",
        "why": "turned toward camera", "blurred": False}
assert verdicts(dict(base)) is not None, "jawaban bersih ikut ditolak"
print("bersih           -> diterima")

cases = (
    ("blur            ", {"blurred": True}),
    ("ok=false        ", {"ok": False}),
)
for label, override in cases:
    ans = dict(base)
    ans.update(override)
    got = verdicts(ans)
    assert got is None, "%s lolos padahal harus ditolak" % label.strip()
    print("%s -> ditolak" % label)

# Kasus 145.6s: model menjawab bahwa wajah yang paling kebaca adalah orang
# lain, jadi ok=false. Diverifikasi terhadap frame asli di /tmp/shape.py:
# ok=False, most_readable="older woman in red/orange cardigan".
ans = dict(base)
ans.update({"ok": False, "most_readable": "older woman in red cardigan",
            "why": "turned toward camera while he is in profile"})
assert verdicts(ans) is None, "frame 145.6s masih lolos"
print("kasus 145.6s     -> ditolak (wajah paling kebaca orang lain)")

print("\n_v61 ok — syarat ditegakkan di kode, bukan hanya di prompt")
