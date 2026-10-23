# scripts/cron — SALINAN, bukan yang dijalankan

Yang benar-benar dijalankan Hermes cron ada di **`~/.hermes/scripts/`** —
tool cron menolak path absolut, jadi wrapper harus tinggal di sana. Folder ini
cuma **salinan untuk riwayat git**, karena `~/.hermes/scripts/` nol version
control: tiga script di sini diubah 23 Okt 2026 untuk memasang pagar memori,
dan tanpa salinan ini perubahan itu tidak punya jejak sama sekali.

## Jebakan: dua salinan bisa menyimpang tanpa suara

Kalau `~/.hermes/scripts/x.sh` diedit dan folder ini tidak, git akan
memperlihatkan versi yang **tidak pernah jalan** — persis kelas kesalahan
"file di disk bukan kode yang dieksekusi" yang sudah beberapa kali menipu di
repo ini. Jadi:

```bash
# cek penyimpangan (wajib nol keluaran)
for f in scripts/cron/*.sh; do
  diff -q "$f" "$HOME/.hermes/scripts/$(basename "$f")" || echo "BEDA: $f"
done
```

Gate `tests/_v95_cron_salinan_sinkron.py` menjalankan pembandingan itu, jadi
penyimpangan bikin suite merah daripada diam.

## Isi

| file | job cron | perubahan 23 Okt 2026 |
|---|---|---|
| `clipper_render_tick.sh` | `4688dbed4c44` | `CLIPPER_FFMPEG` → pagar memori |
| `bio1_render_broll.sh` | `455ebcd2fa17` | pagar + `trap` pemulihan `.full` |
| `stockstory_scene_filler.sh` | `8cc06f546710` | PATH shim (pemanggil tanpa env hook) |
| `audit_watch.sh` | `6831dcb85dee` | tidak diubah; disalin untuk kelengkapan |
