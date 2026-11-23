# 시니어 숏드라마 제작 엔진

훈작가식 9:16 대화 드라마를 제작하기 위한 별도 프로젝트. 영상 대본과 장면 계획을 확정한 뒤, 첫 프레임 이미지는 제작자가 제공하고 Grok에서 각 장면을 세로 MP4로 만든다. 엔진은 인물별 음성, 장면 길이, 자막, 컷, 선택적 BGM을 합쳐 최종 MP4를 출력한다.

`example/episode.json`의 7샷은 **작동 확인용 일부 장면**이다. 2~3분 완성 대본이나 실제 첫 프레임 PNG가 아니다. 본편은 장면별 대사를 확정한 뒤 20~40개 안팎의 영상 자산으로 제작한다.

첫 본편 후보는 `episodes/001-wedding-father/episode.json`(25장면)이다. 대본은 같은 폴더의 `storyboard.md`, 첫 프레임과 Grok 파일 인계는 `GROK_HANDOFF.md`를 따른다. `plan` 명령이 `shot_prompts.md`를 생성한다.

## 한 편의 제작 흐름

1. `episode.json`에 인물·대사·반응 컷·장면 설명을 작성한다.
2. `python drama_engine.py plan episode.json`으로 첫 프레임/Grok 프롬프트와 필요한 파일명을 확인한다. 각 `frames/S01.png`은 별도로 제작한다.
3. `python drama_engine.py prepare episode.json`으로 Typecast에서 인물별 TTS를 만들고 실제 길이를 측정한다. API를 쓰지 않을 경우 `audio/S01-01.mp3` 등을 직접 넣어도 된다.
4. 사용자가 첫 프레임을 Grok에 넣고 장면별 9:16 영상을 생성해 `videos/S01.mp4` 등에 저장한다.
5. `python drama_engine.py check episode.json`으로 누락과 길이를 확인한다.
6. `python drama_engine.py render episode.json`으로 `output/final.mp4`를 만든다.

**입력 원칙:** 대사와 음성 길이가 편집 시간의 기준이다. 장면에 무대사 표정·행동이 필요하면 `pause_before`, `pause_after`, `hold_sec`을 명시한다. 입술이 보이는 대사 샷의 립싱크는 생성 MP4 품질에 달려 있으므로 말하는 얼굴을 검수하고 필요한 샷만 다시 만든다. 음성은 Typecast의 각 인물 목소리로 고정한다.

## 요구사항

- Python 3.10+ 및 FFmpeg/FFprobe가 PATH에 있어야 한다.
- Typecast를 쓸 경우 `TYPECAST_API_KEY` 환경 변수. 프로젝트에 키를 저장하지 않는다.
- 기본 캔버스: 1080×1920, 30fps, H.264/AAC.
- `episode.json`의 상대 경로는 JSON이 있는 폴더를 기준으로 한다.

## JSON 핵심 필드

- `actors`: 등장인물별 `voice_id`.
- `shots`: 순서대로 `id`, `prompt`, `lines`. 각 line은 `actor`, `text`, 선택적 `audio`를 가진다.
- `hold_sec`: 대사가 없는 장면 길이. 대사 장면에서는 최소 전체 길이로 작동한다.
- `pause_before`, `pause_after`: 해당 장면에서 발화 앞뒤 호흡.
- `video`: 기본값 `videos/{id}.mp4`.
- `first_frame`: 기본값 `frames/{id}.png`. 이미지 없이 프롬프트만 쓸 장면은 `null`.
- `music`: 선택적 BGM 경로. `music_db`는 기본 -23.
- `scene_audio_db`: 원본 Grok 영상의 현장음. 기본 음소거(-100). 대사가 들어 있으면 그대로 쓰지 않는다.

Typecast 문자 타임스탬프가 있는 음성은 자막 구절의 첫/마지막 글자에 맞춘다. 사용자가 MP3를 직접 넣고 타임스탬프 파일이 없으면 발화 길이에 비례해 자막을 배분하므로 최종 렌더를 눈으로 검수한다. 대사별 `emotion`, `emotion_intensity`, `tempo`를 설정할 수 있다.

## 검수

`check`는 누락 영상과 길이 차이를 보고한다. 원본보다 목표 장면이 길면 최대 1.35배까지 느리게 재생한다. 그 이상이면 장면을 나누거나 더 긴 영상을 준비해야 한다. 렌더 후 첫 3초, 모든 화자 변경, 공개·반전 지점, 마지막 10초를 실제 화면과 소리로 확인한다.

이 엔진은 영상 생성 자체를 Grok에서 자동 실행하지 않는다. 기존 건축 쇼츠에서 검증한 사용자 참여 방식이며, 영상 원본이 들어오면 편집과 최종 출력은 자동이다.

