#!/usr/bin/env bash
# Measure music level in windows that contain ONLY music vs windows with speech.
# Oden's complaint was "musik nya terlalu kencang gak ni" — the answer is a
# RATIO, not a mix level, so each window has to be isolated.
#
# -v error swallows volumedetect's output (it logs at info); this cost a round.
cd /home/ubuntu/clipper || exit 1
N=jobs/clip_1791642180_122_small.mp4

echo "music-only windows (no speech underneath):"
for seg in "0.2 2.2 hook-music" "31.5 4.5 outro-music"; do
    set -- $seg
    ffmpeg -nostats -v info -ss "$1" -t "$2" -i "$N" -af volumedetect \
        -f null /dev/null 2>/tmp/v.txt
    printf "  %-14s mean %8s  peak %8s\n" "$3" \
        "$(grep -o 'mean_volume: [-0-9.]*' /tmp/v.txt | cut -d' ' -f2)" \
        "$(grep -o 'max_volume: [-0-9.]*' /tmp/v.txt | cut -d' ' -f2)"
done

echo
echo "speech windows (music ducked to 20%):"
for seg in "8 6 speech-1" "20 6 speech-2"; do
    set -- $seg
    ffmpeg -nostats -v info -ss "$1" -t "$2" -i "$N" -af volumedetect \
        -f null /dev/null 2>/tmp/v.txt
    printf "  %-14s mean %8s  peak %8s\n" "$3" \
        "$(grep -o 'mean_volume: [-0-9.]*' /tmp/v.txt | cut -d' ' -f2)" \
        "$(grep -o 'max_volume: [-0-9.]*' /tmp/v.txt | cut -d' ' -f2)"
done
