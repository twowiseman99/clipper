# Console render — cara pakai

Web UI buat bikin klip tanpa nyentuh terminal. Dipakai tim kecil; akun
dibikin manual, ga ada halaman daftar.

## Buka

```
http://<ip-vps>:8001
```

Browser bakal nanya user + sandi. Akun ada di
`~/.hermes/clipper-console.env` (mode 600, cuma kebaca pemilik box):

```
cat ~/.hermes/clipper-console.env
```

Nambah orang: edit file itu, pola `nama:sandi` dipisah koma, terus

```
systemctl --user restart clipper-console
```

Sandi disimpen apa adanya di file itu — ini bukan sistem akun publik, cuma
pintu buat tim yang udah saling kenal. Jangan pakai sandi yang lu pakai di
tempat lain.

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

Link YouTube atau Google Drive. Link lain ditolak dengan pesan jelas.

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
