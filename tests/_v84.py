"""_v84: alat ganti sandi console + pembandingan sandi yang timing-safe.

Yang dijaga di sini bukan "scriptnya jalan". Tiga hal yang kalau rusak
bikin kerugian nyata, dan dua di antaranya rusaknya DIEM:

1. **File akun ga boleh rusak sebagian.** Satu baris `CLIPPER_CONSOLE_USERS`
   yang kebentuk salah bikin console tetep nyala tapi NOLAK SEMUA ORANG.
   Dan baris lain di file itu (`NINEROUTER_API_KEY`) kalau kehapus bikin
   hook/judul balik ke transkrip tanpa bilang apa-apa.

2. **Daftar akun kosong harus ditolak**, bukan ditulis. Nulis daftar kosong
   itu ngunci diri sendiri keluar dari console.

3. **Sandi dibandingin timing-safe.** Begitu console kebuka ke internet
   lewat tunnel, `==` yang short-circuit itu jalan nebak sandi per
   karakter.

Tes ini kerja di file env TIRUAN, bukan punya operator.
"""
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    sys.path.insert(0, BASE)
    sys.path.insert(0, os.path.join(BASE, "scripts"))
    tmp = tempfile.mkdtemp(prefix="v84_")
    env = os.path.join(tmp, "console.env")
    with open(env, "w", encoding="utf-8") as f:
        f.write('# komentar yang harus selamat\n'
                'CLIPPER_CONSOLE_USERS="dalmi:aaa,oden:bbb"\n'
                'NINEROUTER_API_KEY=jangan-hilang\n')
    os.environ["CLIPPER_CONSOLE_ENV"] = env

    import console_passwd as cp
    cp.ENV_PATH = env

    # --- 1. baca akun dari baris berkutip -----------------------------
    baris, akun = cp.baca_env(env)
    assert akun == {"dalmi": "aaa", "oden": "bbb"}, akun

    # --- 2. ganti satu sandi, sisanya + baris lain WAJIB selamat ------
    akun["oden"] = "sandi-baru-yang-panjang"
    cp.tulis_env(baris, akun, env)
    isi = open(env, encoding="utf-8").read()
    assert "NINEROUTER_API_KEY=jangan-hilang" in isi, \
        "baris env lain kehapus waktu ganti sandi"
    assert "# komentar yang harus selamat" in isi, "komentar kehapus"
    _, akun2 = cp.baca_env(env)
    assert akun2 == {"dalmi": "aaa", "oden": "sandi-baru-yang-panjang"}, akun2
    # Izin file ga boleh longgar: isinya sandi mentah.
    assert oct(os.stat(env).st_mode & 0o777) == "0o600", \
        oct(os.stat(env).st_mode & 0o777)

    # --- 3. daftar kosong DITOLAK, file lama ga disentuh --------------
    sebelum = open(env, encoding="utf-8").read()
    try:
        cp.tulis_env(baris, {}, env)
        raise AssertionError("daftar akun kosong diterima — itu ngunci "
                             "diri sendiri keluar dari console")
    except SystemExit:
        pass
    assert open(env, encoding="utf-8").read() == sebelum, \
        "file keubah padahal penulisan ditolak"

    # --- 4. nama/sandi dengan koma ditolak ----------------------------
    # Koma itu pemisah akun; satu koma di dalam sandi bikin SEMUA akun
    # sesudahnya kebaca ngaco.
    for jahat in ({"a,b": "panjangbanget"}, {"a": "sandi,koma"}):
        try:
            cp.tulis_env(baris, jahat, env)
            raise AssertionError("koma diterima: %r" % jahat)
        except SystemExit:
            pass

    # --- 5. file env yang belum ada ga bikin meledak ------------------
    kosong = os.path.join(tmp, "belum-ada.env")
    b2, a2 = cp.baca_env(kosong)
    assert (b2, a2) == ([], {}), (b2, a2)

    # --- 6. PEMBANDINGAN SANDI TIMING-SAFE ---------------------------
    # Dibaca dari SUMBER render_console.py, bukan dari ingatan: comment
    # yang bilang "udah aman" ga ngamanin apa-apa kalau kodenya balik ke
    # `==`.
    src = open(os.path.join(BASE, "render_console.py"),
               encoding="utf-8").read()
    blok = src[src.index("def _siapa("):src.index("def _minta_sandi(")]
    assert "compare_digest" in blok, \
        "pembandingan sandi balik ke == (short-circuit, bocorin prefix)"
    assert "USERS[nama] == sandi" not in blok, blok[-300:]

    # Dan dia masih BENERAN mutusin bener/salah, bukan cuma 'aman'.
    import base64

    class _Req:
        def __init__(self, auth):
            self.headers = {"authorization": auth} if auth else {}

    def auth(nama, sandi):
        return "Basic " + base64.b64encode(
            ("%s:%s" % (nama, sandi)).encode()).decode()

    os.environ["CLIPPER_CONSOLE_USERS"] = "zed:sandi-bener-panjang"
    for m in ("render_console",):
        sys.modules.pop(m, None)
    import render_console as rc
    assert rc._siapa(_Req(auth("zed", "sandi-bener-panjang"))) == "zed"
    assert rc._siapa(_Req(auth("zed", "sandi-salah"))) is None
    assert rc._siapa(_Req(auth("zed", ""))) is None
    assert rc._siapa(_Req(auth("ga-ada", "sandi-bener-panjang"))) is None
    assert rc._siapa(_Req(None)) is None
    assert rc._siapa(_Req("Basic bukan-base64!!")) is None
    # Header tanpa titik dua ga boleh bikin exception.
    assert rc._siapa(_Req("Basic " + base64.b64encode(b"tanpatitikdua")
                          .decode())) is None

    # --- 7. VERIFIKATOR GA BOLEH NEMBAK ENDPOINT TANPA PAGAR ---------
    # Ini kena waktu beneran ganti sandi: verifikatornya nembak `/sehat`
    # dan dapet 200/200/200, terus bilang "GAGAL diverifikasi" -- padahal
    # yang salah alatnya, bukan sandinya. `/sehat` sengaja kebuka buat
    # health check, jadi SELALU 200 dan ga bisa mbuktiin apa pun soal
    # kredensial.
    # Yang diperiksa BARIS KODE, bukan prosa: percobaan pertama tes ini
    # kena ke komentar yang justru nerangin kenapa /sehat ga dipakai.
    kode = open(os.path.join(BASE, "scripts", "console_passwd.py"),
                encoding="utf-8").read()
    blok = kode[kode.index("def cek_http("):].split("def main(")[0]
    baris_kode = [ln for ln in blok.splitlines()
                  if ln.strip() and not ln.lstrip().startswith("#")]
    assert not any("/sehat" in ln for ln in baris_kode), \
        ("verifikator sandi nembak /sehat yang tanpa pagar: %s"
         % [ln.strip() for ln in baris_kode if "/sehat" in ln])

    # --- 8. /sehat ga boleh bocorin jumlah akun ke publik ------------
    # Begitu console kebuka ke internet, jumlah akun itu kabar gratis
    # buat yang mau nebak sandi.
    src_sehat = src[src.index('@app.get("/sehat")'):]
    src_sehat = src_sehat[:src_sehat.index("if __name__")]
    assert "_siapa(request)" in src_sehat, \
        "/sehat ga ngebedain yang login dan yang enggak"
    import json as _json

    class _R0:
        headers = {}
    tanpa = rc.sehat(_R0())
    assert "user_kepasang" not in _json.dumps(tanpa), tanpa
    assert "nunggu" not in _json.dumps(tanpa), tanpa
    dengan = rc.sehat(_Req(auth("zed", "sandi-bener-panjang")))
    assert dengan.get("user_kepasang") == 1, dengan

    print("_v84 ok: file akun aman, daftar kosong ditolak, sandi timing-safe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
