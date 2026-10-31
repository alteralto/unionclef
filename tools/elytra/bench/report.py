"""One captioned video from bench clips and text cards (the way docs/VIDEO_REPORTS.md asks: every clip
names its event, numbers on a card, English only).

    python report.py storyboard.json out.mp4

storyboard.json: a list of
    {"card": ["title line", "line", ...], "seconds": 4}
    {"clip": "path.mp4", "from": 0, "to": 25, "title": "...", "caption": "...", "speed": 1}
"""
import json
import pathlib
import subprocess
import sys
import tempfile

from bench import FFMPEG

FONT = "C\\:/Windows/Fonts/segoeui.ttf"
FONT_B = "C\\:/Windows/Fonts/segoeuib.ttf"
W, H, FPS = 1920, 1080, 30


def textfile(tmp, name, text):
    p = pathlib.Path(tmp) / name
    p.write_text(text, encoding="utf-8")
    return p.as_posix().replace(":", "\\:")


def card(tmp, i, lines, seconds):
    out = pathlib.Path(tmp) / f"{i:02d}.mp4"
    draws = []
    y0 = H // 2 - 60 * len(lines) // 2
    for j, line in enumerate(lines):
        f = textfile(tmp, f"c{i}_{j}.txt", line)
        size, font = (64, FONT_B) if j == 0 else (40, FONT)
        draws.append(f"drawtext=fontfile='{font}':textfile='{f}':fontsize={size}:fontcolor=white:"
                     f"x=(w-text_w)/2:y={y0 + j * 70 + (0 if j == 0 else 30)}")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c=0x16181d:s={W}x{H}:r={FPS}:d={seconds}", "-vf", ",".join(draws),
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


def clip(tmp, i, c):
    out = pathlib.Path(tmp) / f"{i:02d}.mp4"
    speed = c.get("speed", 1)
    t = textfile(tmp, f"t{i}.txt", c["title"])
    cap = textfile(tmp, f"k{i}.txt", c.get("caption", ""))
    vf = (f"setpts=PTS/{speed},fps={FPS},scale={W}:{H},"
          f"drawbox=x=0:y=0:w=iw:h=118:color=black@0.55:t=fill,"
          f"drawtext=fontfile='{FONT_B}':textfile='{t}':fontsize=46:fontcolor=white:x=40:y=14,"
          f"drawtext=fontfile='{FONT}':textfile='{cap}':fontsize=30:fontcolor=0xd8dde6:x=40:y=72")
    if speed != 1:
        badge = textfile(tmp, f"s{i}.txt", f"x{speed:g}")
        vf += f",drawtext=fontfile='{FONT_B}':textfile='{badge}':fontsize=40:fontcolor=0xffc04a:x=w-text_w-40:y=34"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(c.get("from", 0)),
                    "-to", str(c.get("to", 9999)), "-i", c["clip"], "-an", "-vf", vf,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


def main():
    board = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    final = pathlib.Path(sys.argv[2])
    with tempfile.TemporaryDirectory() as tmp:
        parts = [card(tmp, i, s["card"], s.get("seconds", 4)) if "card" in s else clip(tmp, i, s)
                 for i, s in enumerate(board)]
        lst = pathlib.Path(tmp) / "list.txt"
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(lst), "-c", "copy", str(final)], check=True)
    print(final)


if __name__ == "__main__":
    main()
