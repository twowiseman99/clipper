"""render_queue: antrean nyimpen urutan, posisi, dan perkiraan yang jujur.

Yang dijaga di sini bukan angkanya, tapi SIFATNYA:
  - dua pekerja ga boleh ngambil job yang sama
  - nomor urut 1 artinya paling depan
  - perkiraan naik kalau antreannya makin panjang
  - job yang lagi jalan ga bisa dibatalin (ffmpeg udah jalan)
  - state selamet kalau prosesnya mati
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import render_queue as q

tmp = tempfile.mkdtemp(prefix="qtest_")
_n = [0]


def fresh():
    """DB BARU tiap dipanggil.

    Awalnya fungsi ini balikin koneksi ke satu file yang sama, jadi job
    dari bagian tes sebelumnya masih nunggu di antrean dan bikin bagian
    perkiraan gagal (job yang gw kira paling depan ternyata nomor 3).
    Gagalnya bener, yang salah tesnya: tiap bagian harus mulai dari
    antrean kosong.
    """
    _n[0] += 1
    return q.connect(os.path.join(tmp, "q%d.db" % _n[0]))


def same(conn_path_n):
    """Koneksi KEDUA ke DB yang lagi dipakai, buat nguji dua pekerja."""
    return q.connect(os.path.join(tmp, "q%d.db" % conn_path_n))


# --- urutan: yang duluan masuk, duluan diambil -------------------------
conn = fresh()
a = q.submit(conn, "dalmi", "jamet", {"content": "A"})
b = q.submit(conn, "oden", "sedih", {"content": "B"})
c = q.submit(conn, "dalmi", "jamet", {"content": "C"})

assert q.position(conn, a) == 1, "job pertama harus nomor 1"
assert q.position(conn, b) == 2
assert q.position(conn, c) == 3
print("urutan        : 3 job, nomor 1/2/3 sesuai masuknya")

# --- dua pekerja ga boleh ngambil job yang sama ------------------------
w1 = same(1)
w2 = same(1)
j1 = q.claim(w1)
j2 = q.claim(w2)
assert j1 is not None and j2 is not None
assert j1["id"] != j2["id"], (
    "dua pekerja ngambil job yang sama (%s) -- lock-nya ga kerja" % j1["id"])
print("klaim ganda   : pekerja A ambil #%d, pekerja B ambil #%d, beda" %
      (j1["id"], j2["id"]))

# --- job yang udah diambil ga nongol lagi di antrean -------------------
assert q.position(conn, a) == 0, "job running masih dihitung nunggu"
assert q.position(conn, c) == 1, "job terakhir harusnya maju ke nomor 1"
print("maju antrean  : sesudah 2 diambil, #%d naik ke nomor 1" % c)

# --- perkiraan naik kalau antrean panjang ------------------------------
# Catatan: pas ditulis, tes ini sempet gagal karena gw salah baca hasilnya
# sendiri -- nilai 288 yang bikin assert merah itu punya job KETIGA, bukan
# job pertama. Yang dijaga: job paling depan nunggu nol, dan tiap job di
# belakangnya nunggu lebih lama. Angkanya sendiri ga dipatok.
conn2 = fresh()
x = q.submit(conn2, "dalmi", "jamet", {})
y = q.submit(conn2, "dalmi", "jamet", {})
z = q.submit(conn2, "dalmi", "jamet", {})
e1 = q.eta_seconds(conn2, x)
e2 = q.eta_seconds(conn2, y)
e3 = q.eta_seconds(conn2, z)
assert e1 == 0, "job paling depan harusnya ga nunggu siapa-siapa, dapet %.0f" % e1
assert e2 > e1, "perkiraan #2 (%.0f) ga lebih lama dari #1 (%.0f)" % (e2, e1)
assert e3 > e2, "perkiraan #3 (%.0f) ga lebih lama dari #2 (%.0f)" % (e3, e2)
print("perkiraan     : #1 = %.0f, #2 = %.0f, #3 = %.0f detik (naik terus)"
      % (e1, e2, e3))

# --- perkiraan ikut sisa render yang LAGI jalan ------------------------
# Jebakan yang gw kena pas nulis ini: gw banding "sebelum claim" vs
# "sesudah claim" dan dapet 144 vs 144, kelihatan kayak bug. Padahal
# sesudah claim si penunggu MAJU ke nomor 1, jadi dua angka itu ngukur
# keadaan yang beda. Sifat yang bener: job nomor 1 yang nungguin render
# berjalan TIDAK boleh dikasih perkiraan nol -- dia masih harus nunggu
# render yang lagi jalan kelar.
conn2b = fresh()
p = q.submit(conn2b, "dalmi", "jamet", {})
nunggu = q.submit(conn2b, "oden", "jamet", {})
q.claim(conn2b)
assert q.position(conn2b, nunggu) == 1, "penunggu harusnya udah nomor 1"
eta_nomor1 = q.eta_seconds(conn2b, nunggu)
assert eta_nomor1 > 0, (
    "nomor 1 dikasih perkiraan nol padahal ada render lagi jalan -- orang "
    "bakal ngira gilirannya sekarang")
print("sisa running  : nomor 1 tetep dikasih %.0f detik, bukan nol" % eta_nomor1)

# KONTROL: tanpa render jalan, nomor 1 memang nol.
conn2c = fresh()
solo = q.submit(conn2c, "dalmi", "jamet", {})
assert q.eta_seconds(conn2c, solo) == 0, (
    "antrean kosong tapi nomor 1 disuruh nunggu")
print("kontrol       : antrean kosong, nomor 1 = 0 detik")

# --- perkiraan pakai angka hasil ukur, bukan angka karangan ------------
assert 120 <= q.MEDIAN_RENDER_SEC <= 180, (
    "MEDIAN_RENDER_SEC %.0f ga masuk akal; dari 257 render median 144 detik"
    % q.MEDIAN_RENDER_SEC)
print("dasar angka   : median %.0f detik, dari ukuran nyata" % q.MEDIAN_RENDER_SEC)

# --- job yang lagi jalan GA BISA dibatalin -----------------------------
conn3 = fresh()
r = q.submit(conn3, "dalmi", "jamet", {})
q.claim(conn3)
assert q.cancel(conn3, r, "dalmi") is False, (
    "job running kebatalin -- ffmpeg-nya udah jalan, ini ninggalin file "
    "setengah jadi")
print("batal running : ditolak, bener")

# --- job yang nunggu BISA dibatalin, tapi cuma sama yang punya ---------
w = q.submit(conn3, "dalmi", "jamet", {})
assert q.cancel(conn3, w, "oden") is False, "orang lain bisa batalin job gw"
assert q.cancel(conn3, w, "dalmi") is True, "yang punya ga bisa batalin"
print("batal nunggu  : orang lain ditolak, yang punya boleh")

# --- state selamet kalau prosesnya mati --------------------------------
conn4 = fresh()
_db_n = _n[0]
s = q.submit(conn4, "dalmi", "jamet", {"content": "selamet"})
conn4.close()
conn5 = same(_db_n)
got = q.get(conn5, s)
assert got and got["status"] == "waiting", "antrean ilang sesudah koneksi tutup"
print("tahan mati    : job #%d masih ada sesudah koneksi ditutup" % s)

# --- pekerja mati di tengah: job running ga nyangkut selamanya ---------
conn6 = fresh()
m = q.submit(conn6, "dalmi", "jamet", {})
q.claim(conn6)
conn6.execute("UPDATE jobs SET started_at=? WHERE id=?",
              (time.time() - 7200, m))
conn6.commit()
n = q.reap_stale(conn6)
assert n == 1, "job running umur 2 jam ga dibersihin"
assert q.get(conn6, m)["status"] == "failed"
print("pekerja mati  : job nyangkut 2 jam ditandai gagal, antrean lanjut")

# --- KONTROL: job running yang masih wajar JANGAN dibunuh --------------
conn7 = fresh()
k = q.submit(conn7, "dalmi", "jamet", {})
q.claim(conn7)
assert q.reap_stale(conn7) == 0, (
    "job yang baru mulai ikut dibunuh -- ini bakal matiin render yang sehat")
print("kontrol       : job yang baru mulai TIDAK dibunuh")

print("\n_v80 ok — antrean jujur: urutan, klaim tunggal, perkiraan naik, "
      "batal yang bener, tahan proses mati")
