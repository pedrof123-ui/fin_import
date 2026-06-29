GOAL: The goal is to create an enhancement to Earnings Calls Summary feature in Finview to transcribe a user provided mp4 file in data folder and save the transcription in the earnings call transcripts database

Use the Openrouter transcribe API with model openai/whisper-large-v3-turbo

First convert mp4 to mp3. If mp3 greater than 25MB, it needs to be chunked before submitting to the API. Then the transcript chunks need to be combined before saving in the database and creating the agent summary.

The following code is sample code for reference only. You are welcome to make changes to fit guidelines, improve and fit the project structure and features:

import base64
import os
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY is not set")

chunk_dir = Path("../data/earnings_calls_audio/chunks")
chunk_paths = sorted(chunk_dir.glob("chunk_*.mp3"))

if not chunk_paths:
    raise RuntimeError(f"No chunks found in {chunk_dir}")

session = requests.Session()

retries = Retry(
    total=3,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["POST"],
)

session.mount("https://", HTTPAdapter(max_retries=retries))

headers = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
}

def transcribe_chunk(path: Path) -> str:
    size_mb = path.stat().st_size / 1024 / 1024
    print(f"Transcribing {path.name} ({size_mb:.2f} MB)")

    with open(path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")

    response = session.post(
        "https://openrouter.ai/api/v1/audio/transcriptions",
        headers=headers,
        json={
            "model": "openai/whisper-large-v3-turbo",
            "input_audio": {
                "data": audio_b64,
                "format": "mp3",
            },
            "language": "en",
        },
        timeout=(20, 300),
    )

    print("Status:", response.status_code)

    if not response.ok:
        print(response.text[:2000])
        response.raise_for_status()

    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError:
        raise RuntimeError(
            f"Non-JSON response for {path.name}: "
            f"{response.text[:1000]}"
        )

    return data.get("text", "")

all_text = []

for chunk_path in chunk_paths:
    text = transcribe_chunk(chunk_path)
    all_text.append(f"\n\n## {chunk_path.name}\n\n{text}")

output_path = Path("../data/earnings_calls_audio/cerebras_earnings_call_2026-06-23_transcript.md")
output_path.write_text("\n".join(all_text), encoding="utf-8")

print(f"Saved transcript to: {output_path}")



Create a PLAN.md with testable phases before implementing and mark PLAN.md as phases are completed.

Please fell free to ask questions and make recommendations to improve.





