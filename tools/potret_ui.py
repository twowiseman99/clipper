#!/usr/bin/env python3
"""Screenshot console lewat HTTPS, apa adanya -- buat ditunjukin ke operator.

Dipotret dari URL hidup (bukan HTML tiruan) supaya yang kelihatan itu yang
beneran dikirim server: CSS, font, lebar kolom, semuanya.

Dua ukuran: desktop 1280 dan HP 390. Yang kedua yang penting, karena
operator mau ini jalan di domain dan dibuka dari HP.
"""
import os
import re
import sys

from playwright.sync_api import sync_playwright

HOST = "43-157-203-118.nip.io"
KELUAR = "/tmp/ui"
os.makedirs(KELUAR, exist_ok=True)

env = open(os.path.expanduser("~/.hermes/clipper-console.env")).read()
m = re.search(r'^CLIPPER_CONSOLE_USERS="([^"]*)"', env, re.M)
nama, sandi = m.group(1).split(",")[0].split(":", 1)

HALAMAN = [
    ("form", "/", 1280, 900),
    ("form-hp", "/", 390, 844),
    ("job", "/job/5", 1280, 1100),
    ("job-hp", "/job/5", 390, 844),
]

with sync_playwright() as p:
    b = p.chromium.launch()
    for label, path, w, h in HALAMAN:
        ctx = b.new_context(
            viewport={"width": w, "height": h},
            http_credentials={"username": nama, "password": sandi},
            device_scale_factor=2,
            ignore_https_errors=False,
        )
        page = ctx.new_page()
        page.goto("https://%s%s" % (HOST, path), wait_until="load",
                  timeout=30000)
        # Video poster bikin area kosong besar di screenshot; metadata saja.
        page.wait_for_timeout(600)
        out = os.path.join(KELUAR, "%s.png" % label)
        page.screenshot(path=out, full_page=True)
        print("  %-10s %-10s %s byte" % (label, path, os.path.getsize(out)))
        ctx.close()
    b.close()

print("\n  folder:", KELUAR)
