#!/usr/bin/env python3
"""Pull a no-copyright track off YouTube into the BGM folder.

Separate from fetch.py on purpose: that module pulls VIDEO for clipping and
carries a duration cap and a resolution ladder that make no sense for music.
This one takes audio only, writes mp3, and names the file so bgm.py can route
it by mood without a manifest.

    python bgm_add.py --mood hype https://youtu.be/xxxx
    python bgm_add.py --mood emotional --name piano_sad https://youtu.be/yyyy
    python bgm_add.py --list

LICENSING IS ON YOU. yt-dlp cannot tell a Creative Commons track from a major
label master, so this script does not pretend to check. Downloading a
copyrighted song here moves the takedown risk from the clip's captions —
which we just spent a day masking — straight back into its audio. Use tracks
you are actually allowed to use, and keep the attribution line the uploader
asks for.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bgm  # noqa: E402  (path set above)

MAX_SECONDS = 15 * 60  # a BGM bed longer than this is a mix, not a track


def _slug(text):
    """Filesystem-safe lowercase token: 'Sunny Day (Official)' -> sunny_day."""
    text = re.sub(r"\(.*?\)|\[.*?\]", " ", text or "")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return re.sub(r"_+", "_", text)[:40] or "track"


def add(url, mood, name=None, dirpath=None):
    """Download `url` as mp3 into the BGM folder. Returns the written path."""
    import yt_dlp

    if mood not in bgm.MOODS:
        raise SystemExit("mood harus salah satu dari: %s" % ", ".join(bgm.MOODS))

    out_dir = dirpath or bgm.BGM_DIR
    os.makedirs(out_dir, exist_ok=True)

    probe_opts: dict = {"quiet": True, "no_warnings": True, "noplaylist": True}
    # Same client dance as fetch.py: the default web client is SABR-forced and
    # fails with "The page needs to be reloaded".
    probe_opts["extractor_args"] = {"youtube": {"player_client": ["web_embedded"]}}
    probe_opts["remote_components"] = ["ejs:github"]
    cookies = os.environ.get("CLIPPER_COOKIES") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
    if os.path.exists(cookies):
        probe_opts["cookiefile"] = cookies

    with yt_dlp.YoutubeDL(probe_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    secs = (info or {}).get("duration") or 0
    if secs > MAX_SECONDS:
        raise SystemExit("durasi %d menit, kepanjangan buat BGM (maks %d menit)"
                         % (secs // 60, MAX_SECONDS // 60))

    # mood goes in the filename because that is what bgm.py reads when there is
    # no manifest, so a folder stays self-describing after this script exits
    stem = "%s_%s" % (mood, _slug(name or info.get("title")))
    target = os.path.join(out_dir, stem + ".mp3")
    if os.path.exists(target):
        print("sudah ada, dilewati: %s" % target)
        return target

    opts = dict(probe_opts)
    opts.update({
        "format": "bestaudio/best",
        "outtmpl": os.path.join(out_dir, stem + ".%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    if not os.path.exists(target):
        raise SystemExit("download selesai tapi %s tidak ada" % target)

    print("%s  (%s, %.1f MB)" % (target, info.get("title", "?"),
                                 os.path.getsize(target) / 1e6))
    print("uploader: %s" % info.get("uploader", "?"))
    print("PERIKSA LISENSI-nya sebelum dipakai buat klip publik.")
    return target


def show():
    """Print what is currently in the BGM folder, grouped by mood."""
    tracks = bgm.load_tracks()
    print("BGM_DIR = %s" % bgm.BGM_DIR)
    if not tracks:
        print("kosong — klip akan dirender tanpa musik")
        print("mood yang dikenal: %s" % ", ".join(bgm.MOODS))
        return
    by_mood = {}
    for t in tracks:
        for m in (t.get("mood") or ["(tanpa mood)"]):
            by_mood.setdefault(m, []).append(t["file"])
    print("%d track:" % len(tracks))
    for m in bgm.MOODS:
        if m in by_mood:
            print("  %-12s %s" % (m, ", ".join(sorted(by_mood[m]))))
    missing = [m for m in bgm.MOODS if m not in by_mood]
    if missing:
        print("belum ada track: %s" % ", ".join(missing))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("url", nargs="?", help="YouTube URL of the track")
    p.add_argument("--mood", choices=bgm.MOODS, help="mood bucket for this track")
    p.add_argument("--name", help="short name for the file (default: video title)")
    p.add_argument("--list", action="store_true", help="show the BGM folder")
    a = p.parse_args()

    if a.list or not a.url:
        show()
        return
    if not a.mood:
        raise SystemExit("--mood wajib. pilihan: %s" % ", ".join(bgm.MOODS))
    add(a.url, a.mood, a.name)


if __name__ == "__main__":
    main()
