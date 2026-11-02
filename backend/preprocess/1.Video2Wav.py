import os
import sys
import subprocess
from pathlib import Path


# ==================== 單支影片轉 WAV ====================

def convert_one(video_path, output_folder):
    """
    將單支影片轉成 WAV。

    輸出格式：
        - Mono
        - 16 kHz
        - PCM 16-bit
    """

    output_path = output_folder / f"{video_path.stem}.wav"

    cmd = [
        "ffmpeg",
        "-y",

        "-i",
        str(video_path),

        # 不輸出影像
        "-vn",

        # Mono
        "-ac",
        "1",

        # 16 kHz
        "-ar",
        "16000",

        # WAV PCM 16-bit
        "-acodec",
        "pcm_s16le",

        # 單 FFmpeg process thread
        "-threads",
        "1",

        "-loglevel",
        "error",

        str(output_path),
    ]

    try:
        subprocess.run(
            cmd,
            check=True,
        )

    except subprocess.CalledProcessError as e:
        print(f"FFmpeg failed: {video_path}")
        print(e)
        return False

    # ==================== 驗證輸出 ====================

    if not output_path.exists():
        print(f"WAV not created: {output_path}")
        return False

    if output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)

        print(f"WAV is empty: {output_path}")
        return False

    print(f"WAV Done: {video_path.stem}")
    print(f"Saved: {output_path}")

    return True


# ==================== Main ====================

def main():

    # pipeline.py 必須傳入 video_path
    if len(sys.argv) < 2:
        print("Missing video path")
        sys.exit(1)

    video_path = Path(
        sys.argv[1]
    ).resolve()

    if not video_path.exists():
        print(f"Video not found: {video_path}")
        sys.exit(1)

    # backend/preprocess/1.Video2Wav.py
    #              ↓ parent
    # backend/preprocess
    #              ↓ parent
    # backend
    base_dir = Path(os.getenv("WEAVE_WORK_DIR", str(Path(__file__).resolve().parent.parent)))

    output_folder = (
        base_dir
        / "preprocess_output"
        / "audio"
    )

    output_folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 50)
    print("Video to WAV")
    print(f"Video: {video_path}")
    print(f"Output: {output_folder}")
    print("=" * 50)

    success = convert_one(
        video_path,
        output_folder,
    )

    if not success:
        sys.exit(1)

    print("=" * 50)
    print("Video2Wav complete")
    print("=" * 50)


# ==================== Entry ====================

if __name__ == "__main__":
    main()