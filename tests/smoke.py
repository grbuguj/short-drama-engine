"""A real FFmpeg render using two synthetic Grok clips and supplied speech."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def call(*args):
    subprocess.run([str(x) for x in args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


with tempfile.TemporaryDirectory(prefix="drama-smoke-") as temp:
    root = Path(temp)
    (root / "videos").mkdir()
    (root / "audio").mkdir()
    for id_, color, frequency in [("S01", "blue", 440), ("S02", "red", 550)]:
        call("ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=360x640:r=15:d=2.6", "-c:v", "libx264", "-pix_fmt", "yuv420p", root / "videos" / f"{id_}.mp4")
        call("ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration=1.5", "-c:a", "libmp3lame", root / "audio" / f"{id_}-01.mp3")
    data = {
        "slug": "smoke",
        "width": 360,
        "height": 640,
        "fps": 15,
        "actors": {"one": {"voice_id": "unused"}, "two": {"voice_id": "unused"}},
        "shots": [
            {"id": "S01", "lines": [{"actor": "one", "text": "잠깐만요, 누구세요?"}], "hold_sec": 2.0},
            {"id": "S02", "lines": [{"actor": "two", "text": "제가 그 사람입니다."}], "hold_sec": 2.0},
        ],
    }
    manifest = root / "episode.json"
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    engine = Path(__file__).resolve().parents[1] / "drama_engine.py"
    call(sys.executable, engine, "render", manifest)
    final = root / "output" / "smoke-final.mp4"
    if not final.is_file() or final.stat().st_size < 10000:
        raise AssertionError("final MP4 missing or empty")
    info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(final)]))
    assert 3.9 < float(info["format"]["duration"]) < 4.2
    assert {item["codec_type"] for item in info["streams"]} >= {"video", "audio"}
    assert "Dialogue:" in (root / "output" / "subtitles.ass").read_text(encoding="utf-8-sig")
    print(f"PASS: {final.stat().st_size} bytes, {info['format']['duration']}s, audio/video/subtitles")

