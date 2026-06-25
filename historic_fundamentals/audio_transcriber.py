"""
Audio transcription utilities for earnings call mp4/mp3 files.

Pipeline: mp4 → mp3 → optional chunking → OpenRouter Whisper API → combined transcript text
"""

import base64
import subprocess
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

WHISPER_MODEL = "openai/whisper-large-v3-turbo"
_OPENROUTER_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
_MAX_MB = 5.0


def convert_to_mp3(src: Path, out_dir: Path) -> Path:
    """Convert mp4 to mp3 using ffmpeg. If src is already mp3, returns src unchanged."""
    if src.suffix.lower() == ".mp3":
        return src
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (src.stem + ".mp3")
    subprocess.run(
        ["ffmpeg", "-i", str(src), "-q:a", "0", "-map", "a", str(out), "-y"],
        check=True,
        capture_output=True,
    )
    return out


def _get_duration(mp3: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(mp3),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def chunk_mp3(mp3: Path, chunk_dir: Path, max_mb: float = _MAX_MB) -> list[Path]:
    """Split mp3 into time-based chunks if it exceeds max_mb. Returns list of paths."""
    size_mb = mp3.stat().st_size / (1024 * 1024)
    if size_mb <= max_mb:
        return [mp3]

    chunk_dir.mkdir(parents=True, exist_ok=True)
    duration = _get_duration(mp3)
    n_chunks = int(size_mb / max_mb) + 1
    chunk_duration = duration / n_chunks

    paths = []
    for i in range(n_chunks):
        start = i * chunk_duration
        out = chunk_dir / f"chunk_{i:03d}.mp3"
        subprocess.run(
            [
                "ffmpeg", "-i", str(mp3),
                "-ss", str(start), "-t", str(chunk_duration),
                "-q:a", "0", str(out), "-y",
            ],
            check=True,
            capture_output=True,
        )
        paths.append(out)

    return paths


def _make_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def transcribe_chunk(chunk: Path, api_key: str, session: requests.Session) -> str:
    with open(chunk, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")

    response = session.post(
        _OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": WHISPER_MODEL,
            "input_audio": {"data": audio_b64, "format": "mp3"},
            "language": "en",
        },
        timeout=(20, 300),
    )
    response.raise_for_status()
    return response.json().get("text", "")


def transcribe_audio(mp3: Path, api_key: str) -> str:
    """
    Chunk mp3 if needed, transcribe all chunks via Whisper, join and return transcript text.
    Chunk files are deleted after successful transcription.
    """
    chunk_dir = mp3.parent / "chunks"
    chunks = chunk_mp3(mp3, chunk_dir)
    session = _make_session()

    parts = []
    for chunk in chunks:
        text = transcribe_chunk(chunk, api_key, session)
        parts.append(text)

    # clean up chunk files (keep the mp3)
    if len(chunks) > 1:
        for chunk in chunks:
            chunk.unlink(missing_ok=True)

    return "\n\n".join(parts)
