#!/usr/bin/env python3
"""Kontrol negatif: matiin escaping, _v85 HARUS merah.

Tes yang tidak pernah terbukti bisa gagal itu bukan tes. Ini mengganti
render_console._e() dengan fungsi identitas (tidak meng-escape apa pun),
menjalankan ulang pemeriksaan escaping _v85, dan menuntut hasilnya GAGAL.
"""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("CLIPPER_CONSOLE_USERS", "tes:tes")

import render_console as rc

# Sabotase: _e jadi identitas.
rc._e = lambda s: s if isinstance(s, str) else str(s)


class BarisPalsu(dict):
    pass


JAHAT = 'Dia bilang "stop" ' + "<" + "script>alert(1)" + "<" + "/script>"
baris = BarisPalsu(id=7, meta=json.dumps({"title": JAHAT, "description": "a & b"}),
                   params="{}", status="done", out_path="/tmp/x.mp4")
html = rc._panel_upload(baris, 7)

raw = re.search(r'value="([^"]*)"', html)
isi = raw.group(1) if raw else ""

# Pemeriksaan yang sama persis dengan yang dipakai _v85 sekarang. Kalau
# sabotase ini tetap lolos, berarti _v85 tidak mengukur escaping.
mentah_muncul = JAHAT in html
escaped_muncul = "&lt;script&gt;" in html
utuh = isi.endswith("&lt;/script&gt;")

print("  value atribut setelah sabotase : %r" % isi[:60])
print("  judul MENTAH muncul di HTML    : %s  (harus True saat disabotase)"
      % mentah_muncul)
print("  bentuk ter-escape muncul       : %s  (harus False)" % escaped_muncul)
print("  value ketangkep utuh           : %s  (harus False)" % utuh)

if mentah_muncul and not escaped_muncul and not utuh:
    print("ok   kontrol negatif: tanpa escaping, KETIGA pemeriksaan _v85 "
          "gagal -> tes itu beneran ngukur escaping")
    sys.exit(0)

print("FAIL kontrol negatif: escaping dimatiin tapi pemeriksaan _v85 masih "
      "lolos -> tes itu ga ngukur apa pun")
sys.exit(1)
