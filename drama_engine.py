#!/usr/bin/env python3
"""Dialogue short drama: Typecast or supplied speech + Grok clips -> final MP4."""

import base64
import json
import math
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import wave
from array import array
from pathlib import Path

RATE = 48000
MAX_STRETCH = 1.35


def run(*args, cwd=None):
    command = [str(part) for part in args]
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"{' '.join(command[:3])} failed:\n{result.stderr[-4000:]}")
    return result.stdout


def probe(file):
    data = json.loads(run("ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", file))
    streams = data.get("streams", [])
    return {
        "duration": float(data["format"]["duration"]),
        "video": any(s["codec_type"] == "video" for s in streams),
        "audio": any(s["codec_type"] == "audio" for s in streams),
    }


def episode_context(path):
    source = Path(path).resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    root = source.parent
    shots = data.get("shots", [])
    if not shots or not isinstance(shots, list):
        raise ValueError("shots must be a nonempty list")
    ids = [s.get("id") for s in shots]
    if any(not re.fullmatch(r"S\d{2,3}", str(value)) for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("shot ids must be unique S01, S02, ...")
    for shot in shots:
        for line in shot.get("lines", []):
            if line.get("actor") not in data.get("actors", {}):
                raise ValueError(f"{shot['id']}: unknown actor {line.get('actor')}")
            if not line.get("text", "").strip():
                raise ValueError(f"{shot['id']}: empty dialogue")
    return root, data


def asset(root, shot, folder, extension):
    key = {"videos": "video", "frames": "first_frame"}.get(folder)
    value = shot.get(key, f"{folder}/{shot['id']}.{extension}")
    return (root / value).resolve()


def audio_path(root, shot, index, line):
    return (root / line.get("audio", f"audio/{shot['id']}-{index:02d}.mp3")).resolve()


def plan(root, data):
    lines = [f"# {data.get('title', data.get('slug', 'Drama'))}", "", "첫 프레임은 해당 장면의 시작 구도입니다. 이미지 안에 자막이나 읽어야 할 글씨를 생성하지 않습니다.", ""]
    for shot in data["shots"]:
        lines += [
            f"## {shot['id']} · {shot.get('kind', 'scene')}",
            f"- 첫 프레임: `{asset(root, shot, 'frames', 'png').relative_to(root)}`",
            f"- Grok 영상: `{asset(root, shot, 'videos', 'mp4').relative_to(root)}`",
            f"- 장면: {shot.get('prompt', '').strip()}",
            "- 대사: " + (" / ".join(f"{x['actor']}: {x['text']}" for x in shot.get("lines", [])) or "(무대사)"),
            "",
        ]
    output = root / "shot_prompts.md"
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"장면 지시: {output} ({len(data['shots'])}개)")


def typecast_line(line, voice_id, destination):
    text = line["text"]
    key = os.getenv("TYPECAST_API_KEY", "").strip()
    if not key:
        raise ValueError("TYPECAST_API_KEY가 없습니다. 오디오 파일을 직접 넣거나 환경 변수를 설정하세요.")
    if voice_id.startswith("TYPECAST_"):
        raise ValueError(f"실제 Typecast voice_id가 필요합니다: {voice_id}")
    payload = {
        "voice_id": voice_id,
        "text": text,
        "model": "ssfm-v30",
        "language": "kor",
        "prompt": {
            "emotion_type": "preset",
            "emotion_preset": line.get("emotion", "normal"),
            "emotion_intensity": float(line.get("emotion_intensity", 1.0)),
        },
        "output": {"audio_format": "mp3", "audio_tempo": float(line.get("tempo", 1.0)), "audio_pitch": 0},
    }
    req = urllib.request.Request(
        "https://api.typecast.ai/v1/text-to-speech/with-timestamps?granularity=char",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Typecast HTTP {error.code}: {error.read(500).decode('utf-8', 'replace')}") from error
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(base64.b64decode(result["audio"]))
    destination.with_suffix(".timing.json").write_text(
        json.dumps({
            "text": text,
            "voice_id": voice_id,
            "emotion": line.get("emotion", "normal"),
            "emotion_intensity": float(line.get("emotion_intensity", 1.0)),
            "tempo": float(line.get("tempo", 1.0)),
            "characters": result.get("characters", []),
            "duration": result.get("audio_duration"),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def prepare(root, data):
    plan(root, data)
    count = 0
    for shot in data["shots"]:
        for i, line in enumerate(shot.get("lines", []), 1):
            dest = audio_path(root, shot, i, line)
            if dest.exists():
                timing = dest.with_suffix(".timing.json")
                if timing.exists():
                    previous = json.loads(timing.read_text(encoding="utf-8"))
                    expected = {
                        "text": line["text"],
                        "voice_id": data["actors"][line["actor"]]["voice_id"],
                        "emotion": line.get("emotion", "normal"),
                        "emotion_intensity": float(line.get("emotion_intensity", 1.0)),
                        "tempo": float(line.get("tempo", 1.0)),
                    }
                    if any(previous.get(key) != value for key, value in expected.items()):
                        raise ValueError(f"{dest}: 대본/목소리가 기존 TTS와 다릅니다. 해당 오디오와 timing 파일을 별도 보관한 뒤 다시 생성하세요.")
                continue
            typecast_line(line, data["actors"][line["actor"]]["voice_id"], dest)
            count += 1
            print(f"TTS: {shot['id']}-{i:02d}")
    print(f"음성 준비 완료: 새 파일 {count}개")


def seconds(value):
    return f"{value:.3f}"


def shot_info(root, shot):
    cues = []
    cursor = max(0, float(shot.get("pause_before", 0)))
    for i, line in enumerate(shot.get("lines", []), 1):
        file = audio_path(root, shot, i, line)
        if not file.is_file():
            raise FileNotFoundError(f"음성 누락: {file}")
        duration = probe(file)["duration"]
        cues.append({"file": file, "start": cursor, "end": cursor + duration, "line": line})
        cursor += duration + max(0, float(line.get("pause_after", 0)))
    target = max(float(shot.get("hold_sec", 0)), cursor + max(0, float(shot.get("pause_after", 0))))
    if target <= 0:
        raise ValueError(f"{shot['id']}: 대사나 hold_sec가 없습니다")
    return target, cues


def check(root, data):
    problems = []
    total = 0
    for shot in data["shots"]:
        video = asset(root, shot, "videos", "mp4")
        try:
            target, _ = shot_info(root, shot)
            total += target
            timing = f"목표 {target:.2f}s"
        except (FileNotFoundError, ValueError) as error:
            timing = "음성 준비 필요"
            problems.append(str(error))
            target = None
        if not video.is_file():
            problems.append(f"영상 누락: {video}")
            print(f"{shot['id']}: {timing}, 영상 없음")
            continue
        info = probe(video)
        if not info["video"]:
            problems.append(f"영상 스트림 없음: {video}")
        if target and target > info["duration"] * MAX_STRETCH:
            problems.append(f"{shot['id']}: {target:.2f}s 목표 > {info['duration']:.2f}s 원본 × {MAX_STRETCH}")
        print(f"{shot['id']}: {timing}, 원본 {info['duration']:.2f}s")
    print(f"예상 길이: {total:.2f}s / 장면 {len(data['shots'])}개 / 문제 {len(problems)}개")
    for problem in problems:
        print(f"- {problem}")
    return not problems


def pcm_samples(file):
    raw = run_bytes("ffmpeg", "-v", "error", "-i", file, "-f", "s16le", "-ac", "1", "-ar", RATE, "pipe:1")
    samples = array("h")
    samples.frombytes(raw)
    return samples


def run_bytes(*args):
    process = subprocess.run([str(x) for x in args], capture_output=True)
    if process.returncode:
        raise RuntimeError(process.stderr.decode("utf-8", "replace")[-4000:])
    return process.stdout


def write_scene_wav(destination, duration, cues):
    frames = math.ceil(duration * RATE)
    output = array("h", [0]) * frames
    for cue in cues:
        sample = pcm_samples(cue["file"])
        start = round(cue["start"] * RATE)
        if start + len(sample) > frames + RATE // 10:
            raise ValueError(f"음성 길이가 장면을 넘습니다: {cue['file']}")
        for i, value in enumerate(sample[: max(0, frames - start)]):
            output[start + i] = value
    with wave.open(str(destination), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(output.tobytes())


def chunks(text, limit=14):
    words = text.strip().split()
    if not words:
        return []
    result, current = [], ""
    for word in words:
        if current and len(current + " " + word) > limit:
            result.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        result.append(current)
    return result


def ass_time(t):
    cs = max(0, round(t * 100))
    return f"{cs // 360000}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


def caption_events(data, timeline):
    result = []
    for scene in timeline:
        for cue in scene["cues"]:
            parts = chunks(cue["line"]["text"])
            weights = [max(1, len(x.replace(" ", ""))) for x in parts]
            total = sum(weights)
            elapsed = 0
            timed = cue["file"].with_suffix(".timing.json")
            characters = json.loads(timed.read_text(encoding="utf-8")).get("characters", []) if timed.is_file() else []
            original = cue["line"]["text"]
            exact = "".join(str(c.get("text", "")) for c in characters) == original and len(characters) == len(original)
            character_cursor = 0
            for part, weight in zip(parts, weights):
                # Prefer Typecast's character timestamps. Imported audio falls back to
                # an explicit proportional approximation and should be reviewed.
                at = original.find(part, character_cursor) if exact else -1
                if at >= 0:
                    relative_start = float(characters[at]["start"])
                    relative_end = float(characters[at + len(part) - 1]["end"])
                    character_cursor = at + len(part)
                    start = scene["start"] + cue["start"] + relative_start
                    end = scene["start"] + cue["start"] + relative_end
                else:
                    start = scene["start"] + cue["start"] + (cue["end"] - cue["start"]) * elapsed / total
                    end = scene["start"] + cue["start"] + (cue["end"] - cue["start"]) * (elapsed + weight) / total
                elapsed += weight
                end = min(scene["end"], max(start + 0.1, end))
                if end - start < 0.35 and result:
                    result[-1][1] = end
                    result[-1][2] += " " + part
                else:
                    result.append([start, end, part])
    return result


def make_ass(destination, data, timeline):
    width, height = int(data.get("width", 1080)), int(data.get("height", 1920))
    font_size = round(width * 0.058)
    y = round(height * 0.74)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Dialogue,Malgun Gothic,{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,5,45,45,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    rows = []
    for start, end, text in caption_events(data, timeline):
        safe = text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")
        rows.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Dialogue,,0,0,0,,{{\\pos({width // 2},{y})}}{safe}")
    destination.write_text(header + "\n".join(rows) + "\n", encoding="utf-8-sig")
    return len(rows)


def render(root, data):
    if not check(root, data):
        raise RuntimeError("누락된 파일이나 길이 문제가 있습니다")
    output = root / "output"
    scenes = output / "scenes"
    scenes.mkdir(parents=True, exist_ok=True)
    timeline = []
    cursor = 0.0
    width, height, fps = int(data.get("width", 1080)), int(data.get("height", 1920)), int(data.get("fps", 30))
    for shot in data["shots"]:
        video = asset(root, shot, "videos", "mp4")
        target, cues = shot_info(root, shot)
        source = probe(video)
        wav = scenes / f"{shot['id']}.wav"
        clip = scenes / f"{shot['id']}.mp4"
        write_scene_wav(wav, target, cues)
        vf = f"trim=duration={source['duration']:.5f},setpts={target / source['duration']:.8f}*(PTS-STARTPTS),scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps},format=yuv420p"
        args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", video, "-i", wav]
        if source["audio"] and float(data.get("scene_audio_db", -100)) > -90:
            db = float(data["scene_audio_db"])
            args += ["-filter_complex", f"[0:v]{vf}[v];[0:a]volume={db}dB,atrim=duration={target:.5f},apad=whole_dur={target:.5f}[amb];[1:a][amb]amix=inputs=2:duration=first:normalize=0[a]", "-map", "[v]", "-map", "[a]"]
        else:
            args += ["-vf", vf, "-map", "0:v:0", "-map", "1:a:0"]
        args += ["-t", seconds(target), "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", str(RATE), "-ac", "2", clip]
        run(*args)
        rendered = probe(clip)["duration"]
        if abs(rendered - target) > 0.08:
            raise RuntimeError(f"{shot['id']}: 렌더 길이 오차 {rendered - target:+.3f}s")
        timeline.append({"id": shot["id"], "start": cursor, "end": cursor + rendered, "duration": rendered, "cues": cues})
        cursor += rendered
        print(f"렌더 장면: {shot['id']} {target:.2f}s")

    ass = output / "subtitles.ass"
    captions = make_ass(ass, data, timeline)
    concat = output / "concat.txt"
    concat.write_text("\n".join(f"file '{(scenes / (shot['id'] + '.mp4')).as_posix()}'" for shot in data["shots"]) + "\n", encoding="utf-8")
    final = output / f"{data.get('slug', 'drama')}-final.mp4"
    music = data.get("music")
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", concat]
    if music:
        music_path = (root / music).resolve()
        if not music_path.is_file():
            raise FileNotFoundError(f"BGM 누락: {music_path}")
        args += ["-stream_loop", "-1", "-i", music_path]
    args += ["-vf", "ass=output/subtitles.ass", "-map", "0:v:0"]
    if music:
        args += ["-filter_complex", f"[1:a]volume={float(data.get('music_db', -23))}dB[m];[0:a][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]", "-map", "[a]"]
    else:
        args += ["-map", "0:a:0"]
    args += ["-t", seconds(cursor), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", final]
    run(*args, cwd=root)
    final_duration = probe(final)["duration"]
    if abs(final_duration - cursor) > 0.15:
        raise RuntimeError(f"완성 파일 길이 오차: 목표 {cursor:.3f}s, 실제 {final_duration:.3f}s")
    print(f"완성: {final} / {cursor:.2f}s / 자막 {captions}개")


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in {"plan", "prepare", "check", "render"}:
        raise SystemExit("사용법: python drama_engine.py {plan|prepare|check|render} path/to/episode.json")
    root, data = episode_context(sys.argv[2])
    action = sys.argv[1]
    if action == "plan":
        plan(root, data)
    elif action == "prepare":
        prepare(root, data)
    elif action == "check":
        sys.exit(0 if check(root, data) else 2)
    else:
        render(root, data)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        raise SystemExit(str(error))

