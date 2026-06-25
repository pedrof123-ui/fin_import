# PLAN: Earnings Call Audio Transcription

## Overview

Add an "Import Audio" workflow to the Earnings Summary feature in Finview. The user places an mp4 (or mp3) file in `data/earnings_calls_audio/`, then enters the filename, ticker, and quarter in the UI. The backend converts to mp3, chunks if > 25MB, transcribes via OpenRouter Whisper, saves to `earnings_transcripts.duckdb`, and returns an LLM-generated summary.

**API model**: `openai/whisper-large-v3-turbo` via OpenRouter  
**Transcription source tag**: `'audio'` (alongside existing `'av'` and `'url'`)

---

## Phase 1: Audio Transcription Module [Complete]

**File**: `historic_fundamentals/audio_transcriber.py` (new)

**Goal**: Self-contained module for mp4→mp3 conversion, chunking, and Whisper transcription. No FastAPI dependency — fully testable in isolation.

**Steps**:
- [x] 1.1 Implement `convert_to_mp3(src: Path, out_dir: Path) -> Path`
- [x] 1.2 Implement `get_duration_seconds(mp3: Path) -> float`
- [x] 1.3 Implement `chunk_mp3(mp3: Path, chunk_dir: Path, max_mb: float = 24.0) -> list[Path]`
- [x] 1.4 Implement `transcribe_chunk(chunk: Path, api_key: str, session: requests.Session) -> str`
- [x] 1.5 Implement `transcribe_audio(mp3: Path, api_key: str) -> str`

**Test**: Manually run on the existing Cerebras mp3 (`data/earnings_calls_audio/cerebras_earnings_call_2026-06-23.mp3`) and verify non-empty text output.

---

## Phase 2: API Endpoint [Complete]

**File**: `api/earnings_router.py` (extend existing)

**Goal**: Add `POST /earnings/import-audio` endpoint that orchestrates transcription, DB save, and LLM summary.

**Steps**:
- [x] 2.1 Add `_AUDIO_DIR` constant pointing to `data/earnings_calls_audio/`
- [x] 2.2 Implement `POST /earnings/import-audio` endpoint
- [x] 2.3 Import `audio_transcriber` module at top of `earnings_router.py`

**Test**: `curl -X POST "http://localhost:8000/earnings/import-audio?ticker=CRBE&quarter=2026Q2&filename=cerebras_earnings_call_2026-06-23.mp3&model=google/gemini-3.5-flash"` and verify 200 response with summary text.

---

## Phase 3: UI [Complete]

**File**: `web/components/EarningsSummaryViewer.tsx` (extend existing)

**Goal**: Add "Import Audio" section below the URL import row.

**Steps**:
- [x] 3.1 Add state: `audioFile`, `audioQuarter`, `transcribing`, `audioInfo`
- [x] 3.2 Implement `handleImportAudio()`
- [x] 3.3 Add UI row with filename input, quarter input, Transcribe button, status text
- [x] 3.4 Reset audio state on ticker change

**Test**: Open Finview, navigate to a ticker, enter the Cerebras filename and quarter, click Transcribe, verify the summary report loads.

---

## Notes

- `ffmpeg` is confirmed available at `/usr/bin/ffmpeg`
- `OPENROUTER_API_KEY` env var already used by existing earnings summarization — no new config needed
- Existing `save_transcript()` in `historic_fundamentals/earnings_transcripts.py` handles upsert — reused as-is
- Chunks stored temporarily in `data/earnings_calls_audio/chunks/` and deleted after transcription
- mp3 conversion output goes into `data/earnings_calls_audio/` alongside the source file
