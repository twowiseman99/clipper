# DESIGN.md — arah visual Clipper

Diisi agent atas izin operator ("bebas lu pakai skill lu, karang sendiri aja
asal antislop"). Setiap pilihan di bawah punya alasan yang bisa dibantah —
kalau ada yang ga cocok, tolak barisnya, jangan ulang semuanya.

Yang ditandai **SETTLED** datang dari jawaban operator, bukan tafsiran agent.

---

## 1. Identitas

Clipper itu apa, buat siapa, dipakai di mana:

> Meja kerja buat tim kecil yang motong video omongan Indonesia jadi short
> 9:16. Dipakai dari browser, satu orang satu kali render, hasilnya ditonton
> di tempat sebelum dikirim ke mana-mana.

Satu kalimat yang bikin dia beda dari dashboard tool lain:

> Dia nunjukin antrean dan ongkos nunggu secara jujur, karena mesinnya cuma
> kuat satu render sekali jalan — bukan nyembunyiin itu di balik spinner.

Alasan: ini satu-satunya hal yang bener-bener beda. Tool render lain jalan di
cloud yang bisa gede-gedein kapasitas; kita 2 core, 2,4 menit median per
render. Kejujuran soal antrean itu fitur, bukan permintaan maaf.

## 2. Karakter

Tiga kata sifat. Satu bilang apa yang Clipper BUKAN:

> **Tenang, terukur, bukan showroom.**

"Bukan showroom" artinya: ga ada hero section, ga ada angka yang digedein
buat gaya, ga ada tombol yang keliatan lebih penting dari fungsinya. Yang
paling gede di layar itu yang paling sering dipencet, bukan yang paling
pengen dipamerin.

## 3. Palet

Warna inti maksimal 2-3 + 1 aksen (R-29). Neutral ga ikut dihitung.

| Peran | Warna | Alasan |
|---|---|---|
| inti 1 | `#12100E` latar gelap | warisan `dashboard.py`; satu tool satu rumah |
| inti 2 | `#64BBA8` teal | `QUOTE_TEAL` di `edit.py` — warna yang beneran muncul di klipnya |
| aksen | `#FFD24A` gold | `PHRASE_COLOR` di `edit.py`; dipakai HEMAT, cuma buat keadaan yang butuh mata |

Diwarisin dari `dashboard.py`, bukan palet sendiri. Alasan: dua halaman beda
palet buat satu tool itu bikin orang ngira dia pindah aplikasi. Dan teal/gold
ini bukan pilihan selera — itu warna yang dilihat penonton di klip jadinya,
jadi mejanya nyambung sama hasilnya.

Aturan pemakaian gold: **cuma satu per layar**. Kalau tombol render gold dan
peringatan juga gold, dua-duanya jadi ga berarti.

## 4. Tipografi

Typeface + alasannya (R-06; "default" bukan alasan):

> `ui-sans-serif, system-ui` buat teks, `ui-monospace` buat angka.

Alasan: halaman ini dibuka dari mesin yang kita ga tau isinya. Webfont berarti
satu request lagi sebelum teks kebaca, padahal halaman ini sering dibuka cuma
buat ngecek "udah kelar belum" — dan pas render jalan, 2 core kepake abis,
jadi tiap byte yang ga perlu kerasa. Font sistem muncul instan.

Angka pakai monospace karena durasi, nomor antrean, dan menit-ke-menit
dibaca sambil dibandingin. Angka proporsional bikin kolom goyang.

## 5. Mood

Terang, gelap, atau toggle (R-21, R-34 — kalau toggle, dua mode wajib jalan):

> **Gelap aja. Ga ada toggle.**

Alasan: `dashboard.py` udah punya dua mode dan itu dua kali kerjaan tiap kali
ada komponen baru. Halaman ini dipakai sambil nonton video — layar gelap lebih
enak dan konsisten sama preview videonya. Toggle setengah jalan lebih buruk
dari satu mode yang rapi (R-34).

## 6. Dial (R-37, Part 3)

| Dial | 1 | 2 | 3 | Pilihan |
|---|---|---|---|---|
| ENERGY | tenang | seimbang | berani | **1 — tenang** |
| RHYTHM | seragam | ada variasi | asimetris | **2 — ada variasi** |
| MOTION | hover aja | transisi | koreografi | **1 — hover aja** |

ENERGY 1: orang buka halaman ini pas lagi nunggu atau lagi kesel sama hasil
render. Halaman yang semangat itu nyebelin di dua keadaan itu.

RHYTHM 2: form, antrean, dan preview beda bobot, jadi ukurannya beda. Tapi ga
asimetris — ga ada alasan bikin orang nyari-nyari letak.

MOTION 1: animasi makan CPU yang lagi dipake ffmpeg. Diukur: render ngabisin
dua core, jadi transisi bakal patah-patah justru di saat paling sering
dilihat. Hover state doang, sisanya diam.

---

## Keputusan yang UDAH diambil (SETTLED, jangan diulang)

- Halaman render = **file baru, port sendiri**, bukan nempel di `dashboard.py`.
- Dua preset: **mengharukan** (`sedih`) dan **jedag jedug** (`jamet`).
- Tiga field: link hook, link isi, gambar outro. Field ketiga cuma nyala buat
  `jamet` — `job.py` udah nolak sendiri kalau dikasih ke `sedih`.
- Field fix: **satu kolom teks bebas + dua kolom waktu (dari-sampai)**, semua
  optional.
- Fix = render ulang penuh, bukan tambal.
- Tombol upload: **disiapin tapi mati** sampai ada akun YouTube.
  `preflight.upload_accounts()` balik kosong, jadi tombol aktif = kontrol mati
  (R-26). Labelnya wajib jujur.
- antislop dipakai mode **DURING**.
- **Akses: tim kecil, akun dibikin manual, ga ada halaman signup.**
- **Antrean: orang kedua masuk antrean, dikasih nomor urut + perkiraan nunggu.**
- Rasio dan resolusi klip **1080x1920 haram diubah** — ga ada kontrol UI yang
  bisa nyentuh itu.

## Angka yang ngebentuk halaman ini (hasil ukur, bukan perkiraan)

Diukur dari 257 render nyata di kotak ini:

| | |
|---|---|
| render median | 2,4 menit |
| render p90 | 3,6 menit |
| render terlama | 6,6 menit |
| jalan bareng | **satu**, `job.py` punya lock (`.job.lock`, `fcntl.flock`) |
| kapasitas | ~25 render/jam |
| CPU | 2 core, ffmpeg ngabisin dua-duanya |

Konsekuensi desain yang ga bisa ditawar:

1. **Request HTTP ga boleh nungguin render.** 2,4 menit itu lebih lama dari
   timeout browser mana pun. Render jadi job terpisah, halaman nanya status.
2. **Antrean wajib nunjukin nomor + perkiraan.** 5 orang klik bareng = yang
   terakhir nunggu 10 menit (p90: 14). Spinner buta bikin orang nge-refresh
   dan ngirim job dobel.
3. **Halaman ikut lambat pas render jalan.** Bukan bug kode, CPU-nya habis.
   Ini ga bisa dikodein biar hilang; obatnya nambah core.

## Yang sengaja TIDAK dibikin

- **Signup, reset password, role.** Tim kecil, akun manual. Fitur akun yang ga
  dipake itu permukaan serangan gratis.
- **Progress bar persen.** `job.py` ga lapor persen, jadi bar yang gerak
  sendiri itu bohong (R-36). Yang ditampilin: tahap sekarang + udah jalan
  berapa lama.
- **Toggle terang/gelap.** Lihat §5.
- **Tombol upload yang aktif.** Lihat SETTLED.
