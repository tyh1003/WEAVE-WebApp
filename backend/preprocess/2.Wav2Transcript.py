import os
import sys
import json
import gc

import torch

from transformers import (
    AutoModelForSpeechSeq2Seq,
    AutoProcessor,
    pipeline,
)


# =========================
# Config
# =========================

MODEL_ID = "openai/whisper-large-v3"

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

BASE_DIR = os.getenv("WEAVE_WORK_DIR", BASE_DIR)

AUDIO_DIR = os.path.join(
    BASE_DIR,
    "preprocess_output",
    "audio"
)

TRANSCRIPT_DIR = os.path.join(
    BASE_DIR,
    "preprocess_output",
    "transcript"
)

os.makedirs(
    TRANSCRIPT_DIR,
    exist_ok=True
)


# =========================
# Device
# =========================

device = "cuda:0" if torch.cuda.is_available() else "cpu"

torch_dtype = (
    torch.float16
    if torch.cuda.is_available()
    else torch.float32
)


# =========================
# Load Whisper
# =========================

def load_whisper():

    print("Loading Whisper...")
    print(f"Model: {MODEL_ID}")
    print(f"Device: {device}")

    model = AutoModelForSpeechSeq2Seq.from_pretrained(
        MODEL_ID,
        dtype=torch_dtype,
        low_cpu_mem_usage=True,
    ).to(device)

    processor = AutoProcessor.from_pretrained(
        MODEL_ID
    )

    asr_pipe = pipeline(
        "automatic-speech-recognition",
        model=model,
        tokenizer=processor.tokenizer,
        feature_extractor=processor.feature_extractor,
        chunk_length_s=30,
        batch_size=1,
        dtype=torch_dtype,
        device=device,
    )

    print("Whisper Loaded")

    return model, processor, asr_pipe


# =========================
# Main
# =========================

def main():

    if len(sys.argv) < 2:
        print("Missing video path")
        sys.exit(1)

    video_path = os.path.abspath(
        sys.argv[1]
    )

    if not os.path.exists(video_path):
        print(
            f"Video not found: {video_path}"
        )
        sys.exit(1)

    vid = os.path.splitext(
        os.path.basename(video_path)
    )[0]


    # =========================
    # Input WAV
    # =========================

    audio_path = os.path.join(
        AUDIO_DIR,
        f"{vid}.wav"
    )

    if not os.path.exists(audio_path):
        print(
            f"Audio not found: {audio_path}"
        )
        sys.exit(1)

    if os.path.getsize(audio_path) == 0:
        print(
            f"Audio is empty: {audio_path}"
        )
        sys.exit(1)


    # =========================
    # Output
    # =========================

    output_path = os.path.join(
        TRANSCRIPT_DIR,
        f"{vid}.json"
    )


    # =========================
    # Whisper
    # =========================

    model = None
    processor = None
    asr_pipe = None

    try:

        model, processor, asr_pipe = load_whisper()

        print("=" * 50)
        print("Whisper Transcription")
        print(f"VID: {vid}")
        print(f"Audio: {audio_path}")
        print("=" * 50)

        result = asr_pipe(
            audio_path
        )

        transcript = result.get(
            "text",
            ""
        ).strip()


        # =========================
        # Save
        # =========================

        record = {
            "vid": vid,
            "transcript": transcript
        }

        with open(
            output_path,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                record,
                f,
                ensure_ascii=False,
                indent=2
            )

        print(f"Transcript: {transcript}")
        print(f"Saved: {output_path}")


    except Exception as e:

        print("Whisper failed")
        print(repr(e))

        sys.exit(1)


    finally:

        # =========================
        # Release VRAM
        # =========================

        if asr_pipe is not None:
            del asr_pipe

        if processor is not None:
            del processor

        if model is not None:
            del model

        gc.collect()

        if torch.cuda.is_available():
            torch.cuda.empty_cache()


    print("=" * 50)
    print("Wav2Transcript complete")
    print("=" * 50)


# =========================
# Entry
# =========================

if __name__ == "__main__":
    main()