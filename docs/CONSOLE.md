# Console render — cara pakai

Web UI buat bikin klip tanpa nyentuh terminal. Dipakai tim kecil; akun
dibikin manual, ga ada halaman daftar.

## Buka

```
http://<ip-vps>:8001
```

Itu dari dalam box. Dari HP / luar rumah, alamatnya **ganti-ganti** —
tanya:

```
clipper-url
```

Dia nyetak alamat yang kepakai sekarang + ngecek dia beneran hidup (401 =
minta sandi, itu yang bener).

**Kenapa ganti-ganti:** tunnel-nya pakai jalur gratis tanpa akun
Cloudflare, dan subdomainnya diundi tiap kali tunnel restart. Terukur:
`kill -9` → alamat pindah dari `gtk-translation-...` ke
`sat-riding-entity-...`, dan yang lama langsung mati (530). Kalau mau
alamat tetap, butuh akun Cloudflare + domain.

Port 80/443 di VPS ini **ketutup dari internet** dan ga perlu dibuka —
tunnel keluar sendiri (outbound), jadi IP VPS ga pernah kelihatan dan
HTTPS-nya dapet gratis. Jangan ganti `CLIPPER_CONSOLE_HOST` ke `0.0.0.0`:
itu malah bikin sandi lu lewat HTTP telanjang.

```
systemctl --user status clipper-tunnel     # hidup?
systemctl --user restart clipper-tunnel    # alamat bakal GANTI
```

Browser bakal nanya user + sandi. Akun ada di
`~/.hermes/clipper-console.env` (mode 600, cuma kebaca pemilik box):

```
cat ~/.hermes/clipper-console.env
```

Nambah orang / ganti sandi: **jangan edit file itu pakai tangan.** Satu
koma kelewat bikin semua akun ga kebaca — console tetep nyala, cuma nolak
semua orang. Pakai:

```
cd ~/clipper
.venv/bin/python scripts/console_passwd.py --list
.venv/bin/python scripts/console_passwd.py --set oden              # diminta, ga keliatan
.venv/bin/python scripts/console_passwd.py --set budi --generate   # acak 20 char
.venv/bin/python scripts/console_passwd.py --remove budi
```

Dia nulis file-nya atomik (mode 600), restart console, lalu **mbuktiin**
lewat HTTP: sandi baru 200, tanpa sandi 401, sandi ngawur 401. Nolak
daftar akun kosong dan nolak sandi di bawah 12 karakter.

Sandi disimpen apa adanya di file itu — ini bukan sistem akun publik, cuma
pintu buat tim yang udah saling kenal. Jangan pakai sandi yang lu pakai di
tempat lain, dan jangan pernah naruh sandi di command line (`-u user:pass`
masuk riwayat shell).

## Isi formnya

Tiga kolom, dua preset.

**mengharukan** — buat cerita sedih/berat. Endingnya melankolis, ga ada
kedip, musiknya ikut. Kolom gambar outro **mati** di preset ini (sengaja:
potret spin itu bahasa hype, salah tempat di klip duka).

**jedag jedug** — buat hype/lucu. Ending hentakan + potret muter. Kolom
gambar outro **nyala**.

| kolom | wajib? | isi |
|---|---|---|
| link hook | ga | video pembuka, bagian paling nyantol. Kosongin = klip tanpa hook, itu hasil yang bener bukan fallback |
| link isi | **iya** | video yang dipotong |
| gambar outro | cuma jedag jedug | foto tegak yang dipegang di akhir |
| BGM | ga | lagu yang dipakai apa adanya. Kosongin = dipilih dari mood klip pakai stok di `background_music/` |

Link YouTube atau Google Drive. Link lain ditolak dengan pesan jelas.

Gambar outro dan BGM sekarang **di-upload** dari browser, bukan diisi path
server. File masuk ke `assets/campaign/<slug>/` — di luar `media/` dan
`jobs/` yang dibuang auto-clean tiap jam 5 pagi, karena file yang lu upload
sendiri ga bisa diunduh ulang.

### BGM yang di-upload ngelewatin satu pengaman

Pemilihan BGM otomatis lewat `bgm.py` punya aturan register: lagu hype ga
boleh nempel di klip duka (`bgm._CLASH`). Lagu yang lu upload **ga bisa
ditolak** aturan itu — dia ga ada di manifest dan kodenya ga bisa denger
isinya. Yang bisa: baca satu kata mood dari **nama file** lu dan ngasih
peringatan kalau bentrok.

Jadi kasih nama yang jujur: `emotional_piano.mp3`, `hype_jedag.mp3`. Nama
tanpa mood (`WhatsApp Audio 2026.mp3`) tetep kepakai, cuma peringatannya ga
bisa dikasih. Mood yang dikenal ada di `bgm.MOODS`.

## Papan campaign

Tab **Campaign** di atas. Daftar campaign dari konten.com, diurut **skor**:

```
skor = Rp per 1.000 views x sisa budget %
```

Bukan CPM mentah, dan itu bukan selera. Diukur: campaign dengan rate
tertinggi di marketplace (Rp15.000, Krakatau) sisa budgetnya **6%** —
duitnya hampir abis, jadi rate gedenya ga bisa diambil. Yang nomor satu
pakai skor: Rp10.000 dengan sisa 97%.

**Kolomnya nulis "Rp / 1.000 views", bukan CPM.** Field API-nya ketulis
`rate_per_million` tapi halaman campaign-nya nulis "Rp10.000 / 1K views"
buat angka yang sama. Namanya bohong; angkanya per seribu. Salah baca di
sini kelirunya 1000x.

**min views merah** = lantai di atas 10.000. Di bawah lantai itu klip ga
dibayar sama sekali, jadi di akun kecil campaign begitu artinya kerja
gratis.

Per campaign lu bisa: tandain **garap**/**lewat**, naro bahan (link video,
gambar, BGM), dan render langsung dari halaman campaign-nya — bahannya
diambil dari aset yang udah ke-upload, dan job-nya kecatet milik campaign
itu.

Papan ga butuh login konten.com (daftar campaign-nya publik). Yang butuh
sesi login cuma SUBMIT klip, dan itu belum ada di console.

## Sesudah klik Render

Lu dibawa ke halaman job. Isinya nomor urut kalau masih nunggu, atau tahap
yang lagi jalan (`unduh`, `transkrip`, `render`).

Kalau orang lain lagi render, lu masuk antrean dan dapet perkiraan nunggu.
Angkanya dari ukuran nyata di box ini — median 2,4 menit per render, dikali
jumlah job di depan lu, plus sisa render yang sedang jalan. Render di VPS
2 core cuma bisa satu-satu; antrean itu yang ngejaga dua ffmpeg ga rebutan.

Kelar = ada tombol unduh, plus daftar peringatan kalau ada. Peringatan
bukan error: misal "freeze outro pakai frame mekanis karena ga ada frame
yang jelas nunjukin subjek". Itu ditampilin apa adanya, bukan disembunyiin.

## Kalau gagal

Pesan aslinya ditampilin, bukan "terjadi kesalahan". Dua yang paling sering:

- **link ga didukung** — bukan YouTube/Drive
- **video ga keunduh** — cookies kedaluwarsa, lapor ke yang pegang box

## Tombol upload

Masih **mati**, dan sengaja dilabelin mati, bukan disembunyiin: belum ada
akun YouTube yang keikat (`preflight.upload_accounts()` balik kosong).
Unduh dulu, upload manual.

## Buat yang pegang box

```
systemctl --user status clipper-console      # hidup?
systemctl --user restart clipper-console     # abis nambah akun
journalctl --user -u clipper-console -n 50   # log
```

Pekerjanya **bukan** bagian dari service ini. Dia cron `clipper-render-tick`
tiap 3 menit, ambil satu job terus exit. Jadi console boleh restart kapan
aja tanpa ngebatalin render yang jalan, dan sebaliknya.

Cek cron: `hermes cron list`. Dua yang relevan:

- `clipper-render-tick` — `*/3`, ngambil job dari antrean
- `clipper-autoclean` — `0 5`, buang unduhan lama

Dua-duanya diem kalau ga ada kerjaan. Diem itu normal, bukan tanda mati.

## Belum ada

- domain + HTTPS (port 443 masih ketutup di panel cloud, belum ada domain)
- upload YouTube
- preview video di halaman sebelum unduh
