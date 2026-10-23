#!/usr/bin/env bash
# Wrapper tipis buat cron. Logicnya ada di repo (clipper/autoclean.py), di
# sini cuma exec -- biar ga ada dua salinan yang bisa beda pendapat.
#
# Cron nolak path absolut, jadi script wajib duduk di ~/.hermes/scripts/.
# Keluaran KOSONG artinya ga ada yang perlu dibuang, dan cron no_agent
# bakal diem. Itu yang diinginkan: cron yang ngomong tiap jam = spam.
set -euo pipefail
cd /home/ubuntu/clipper

# DUA pembersih, beda wilayah, SENGAJA tidak digabung:
#
#   autoclean.py     -> media/ dan jobs/ (klip jadi, unduhan sumber). Daftar
#                       JAGA-nya dibaca dari KODE (tes + KNOWN_ISSUES.md), dan
#                       dia menyisakan N klip terakhir.
#   work_cleanup.py  -> temp_subs_* di akar repo (folder kerja render).
#
# Nol tumpang tindih, dan itu diukur bukan diasumsikan: work_cleanup menolak
# apa pun di luar pola ^temp_subs_[0-9a-f]{6,}$ dan menolak lima wilayah
# dilindungi termasuk media/ dan jobs/ -- 19 kontrol penolakan di
# /tmp/oom/kontrol_cleanup.py, termasuk symlink bernama temp_subs_* yang
# menunjuk KELUAR repo.
#
# Kenapa menempel di job ini, bukan cron baru: operator minta "cek tumpang
# tindih dengan clipper-autoclean, jangan dobel". Satu jadwal, satu pembaca
# log, dan dua pembersih yang tidak bisa saling injak.
#
# work_cleanup jalan DULU: kalau render mati OOM semalam, foldernya yang
# ketinggalan dibuang sebelum autoclean menghitung sisa disk.
.venv/bin/python work_cleanup.py --apply
exec .venv/bin/python autoclean.py --apply
