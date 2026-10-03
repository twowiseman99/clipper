"""Probe: can a face/text gate tell studio apart from field footage?

Measures candidate windows in the three Kompas sources the last render used,
reporting for each: motion, biggest face as a fraction of frame height, and a
crude text-density score from edge density in the lower third (lower-thirds and
map labels live there).

Run before writing the gate, so the thresholds come from this box's real
footage rather than from a guess.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import cv2
import numpy as np

FACE_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "models", "face_detection_yunet_2023mar.onnx")

SOURCES = {
    "vd75nAL4NkE": "Balas Serangan Palestina, Israel Serang Gaza",
    "LPhEuHXVRMY": "Detik-detik Palestina Balas Serangan Israel",
    "gbDzBo9w890": "Israel Balas Serang Jalur Gaza, 232 Tewas",
}


def frame_at(path, at):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(at * fps))
    ok, img = cap.read()
    cap.release()
    return img if ok else None


def face_frac(img):
    """Height of the biggest face as a fraction of frame height."""
    h, w = img.shape[:2]
    det = cv2.FaceDetectorYN_create(FACE_MODEL, "", (w, h), 0.6, 0.3, 5000)
    det.setInputSize((w, h))
    _rc, faces = det.detect(img)
    if faces is None or len(faces) == 0:
        return 0.0, 0
    biggest = max(float(f[3]) for f in faces)
    return biggest / h, len(faces)


def text_score(img):
    """Edge density in the lower third — proxy for captions and graphics."""
    h, w = img.shape[:2]
    strip = img[int(h * 0.62):, :]
    g = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(g, 100, 200)
    return float(np.count_nonzero(edges)) / edges.size


def motion_at(path, at, seconds=2.0):
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{at}", "-t", f"{seconds}",
         "-i", path, "-vf",
         "fps=10,scale=96:-1,tblend=all_mode=difference,signalstats,"
         "metadata=print:key=lavfi.signalstats.YAVG:file=-",
         "-f", "null", "-"], capture_output=True, text=True)
    vals = [float(l.split("=")[-1]) for l in r.stdout.splitlines()
            if "YAVG" in l]
    return sum(vals) / len(vals) if vals else None


print(f"{'source':<14}{'at':>7}{'motion':>8}{'face%':>8}{'faces':>7}{'text':>8}")
print("-" * 52)
for vid in SOURCES:
    path = f"media/broll-{vid}/{vid}.mp4"
    if not os.path.exists(path):
        print(f"{vid:<14} MISSING")
        continue
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True).stdout or 0)
    for frac in (0.25, 0.4, 0.55, 0.7, 0.85):
        at = round(min(dur * frac, dur - 3.0), 2)
        img = frame_at(path, at)
        if img is None:
            continue
        ff, n = face_frac(img)
        print(f"{vid:<14}{at:>7.1f}{motion_at(path, at) or -1:>8.2f}"
              f"{ff * 100:>8.1f}{n:>7}{text_score(img):>8.3f}")
    print()
