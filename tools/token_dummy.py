#!/usr/bin/env python3
"""Bikin token YouTube BOHONGAN biar jalur upload bisa diuji tanpa OAuth.

Gunanya satu: ngebuktiin jalur kode sampai ke API Google. Dengan token ini
request beneran kekirim ke youtube.googleapis.com dan dijawab 401 -- dan 401
itu HASIL YANG BENER di sini, karena artinya semua yang di depan API (import
library, baca token, bangun client, susun body, buka file video) jalan. Yang
ga bisa diuji pakai ini cuma satu: apakah akun lu punya izin upload.

JANGAN dipakai di produksi. Token ini ga akan pernah berhasil upload.

    python tools/token_dummy.py            # bikin
    python tools/token_dummy.py --hapus    # buang
"""
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import upload_youtube  # noqa: E402  (butuh sys.path di atas)

NAMA = "dummy"


def path():
    return os.path.join(upload_youtube.TOKEN_DIR, f"token_{NAMA}.pickle")


def bikin():
    from datetime import datetime, timedelta, timezone

    from google.oauth2.credentials import Credentials

    os.makedirs(upload_youtube.TOKEN_DIR, exist_ok=True)
    # Dua hal yang WAJIB bener biar request-nya beneran kekirim:
    #
    # refresh_token DIKOSONGIN -- load_credentials() cuma manggil
    # creds.refresh() kalau refresh_token ada, dan refresh bakal mental di
    # library (RefreshError) sebelum request upload-nya kekirim.
    #
    # expiry DISET KE MASA DEPAN -- tanpa itu creds.valid False, dan
    # googleapiclient nolak duluan secara lokal. Dengan expiry masih jauh,
    # token-nya dianggap layak coba, kekirim ke Google, dan GOOGLE yang
    # nolak (401). Itu yang mau diukur: jalurnya nyampe API.
    creds = Credentials(
        token="dummy-token-ga-akan-pernah-valid",
        expiry=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=365),
    )
    p = path()
    with open(p, "wb") as f:
        pickle.dump(creds, f)
    os.chmod(p, 0o600)
    return p


def hapus():
    p = path()
    if os.path.exists(p):
        os.remove(p)
        return p
    return None


if __name__ == "__main__":
    if "--hapus" in sys.argv:
        p = hapus()
        print(f"  dibuang: {p}" if p else "  ga ada token dummy")
    else:
        print(f"  dibikin: {bikin()}")
    print(f"  available_accounts(): {upload_youtube.available_accounts()}")
