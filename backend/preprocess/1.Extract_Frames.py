import os
import sys
import subprocess
import glob
import shutil
import logging



# ==================== Logging 設定 ====================

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ==================== 取得影片長度 ====================

def get_video_duration(video_path):
    """
    使用 ffprobe 取得影片長度，單位為秒。
    """

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video_path
            ],
            capture_output=True,
            text=True,
            check=True
        )

        return float(result.stdout.strip())

    except Exception as e:
        logging.error(f"ffprobe failed: {video_path} | {e}")
        return None


# ==================== 產生 Frame 時間點 ====================

def generate_timestamps(duration, middle_frames=14):
    """
    產生影片 Frame 擷取時間點。

    擷取策略固定為：
        1. 第 1 張 Frame：影片開頭。
        2. 中間 14 張 Frame：在影片首尾之間等間距取得。
        3. 第 16 張 Frame：影片片尾。

    因此每部有效影片固定產生 16 個擷取位置：
        1 張開頭 + 14 張中間 + 1 張片尾 = 16 張。

    注意：
        最後一張 Frame 不會直接使用 duration 時間點進行 seek，
        而是交由 extract_last_frame() 擷取影片實際最後一張
        可解碼 Frame。
    """

    total_frames = middle_frames + 2
    interval = duration / (total_frames - 1)

    timestamps = [interval * index for index in range(total_frames)]

    timestamps[0] = 0.0
    timestamps[-1] = float(duration)

    return timestamps


# ==================== 擷取一般指定時間 Frame ====================

def extract_frame_at_timestamp(video_path, timestamp, output_file):
    """
    從指定時間點擷取一張 Frame。

    輸出設定：
        1. 維持影片原始解析度。
        2. 使用 PNG 無損格式輸出。
        3. 不進行 resize。
    """

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.9f}",
                "-i",
                video_path,
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-c:v",
                "png",
                output_file
            ],
            check=True
        )

        return os.path.exists(output_file) and os.path.getsize(output_file) > 0

    except subprocess.CalledProcessError:
        return False


# ==================== 擷取影片最後一張 Frame ====================

def extract_last_frame(video_path, output_file):
    """
    擷取影片實際片尾的最後一張可解碼 Frame。

    使用方式：
        1. 從影片尾端往前讀取最後一小段。
        2. 使用 reverse 將該段影片反轉。
        3. 取得反轉後的第一張 Frame。

    此方法可以避免直接 seek 到 duration 時，
    因為時間點已經位於 EOF 而無法輸出 Frame。
    """

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-sseof",
                "-1",
                "-i",
                video_path,
                "-map",
                "0:v:0",
                "-vf",
                "reverse",
                "-frames:v",
                "1",
                "-c:v",
                "png",
                output_file
            ],
            check=True
        )

        return os.path.exists(output_file) and os.path.getsize(output_file) > 0

    except subprocess.CalledProcessError:
        return False


# ==================== 單部影片 Frame 萃取 ====================

def extract_frames_every_second(video_path, output_folder):
    """
    萃取單部影片的 Frame。

    擷取規則：
        1. 固定取得 16 張 Frame。
        2. 第 1 張為影片開頭 Frame。
        3. 中間 14 張依影片首尾時間等間距取得。
        4. 第 16 張為影片實際最後一張可解碼 Frame。
        5. 不進行 resize，保留影片原始解析度。
        6. 使用 PNG 無損格式儲存。

    輸出結構：
        output_folder/
            video_name/
                frame_0000.png
                frame_0001.png
                ...
                frame_0015.png
    """

    duration = get_video_duration(video_path)

    if duration is None or duration <= 0:
        logging.error(f"Invalid video: {video_path}")
        return

    video_name = os.path.splitext(os.path.basename(video_path))[0]
    video_output_folder = os.path.join(output_folder, video_name)

    timestamps = generate_timestamps(duration, middle_frames=14)
    expected_frames = len(timestamps)


    # ==================== 檢查是否已完成萃取 ====================

    if os.path.exists(video_output_folder):
        existing = glob.glob(os.path.join(video_output_folder, "frame_*.png"))

        if len(existing) == expected_frames and all(os.path.getsize(path) > 0 for path in existing):
            logging.info(f"Skip: {video_name} ({len(existing)} frames already exist)")
            return

        logging.warning(
            f"{video_name}: incomplete frames "
            f"({len(existing)}/{expected_frames}), re-extracting..."
        )

        shutil.rmtree(video_output_folder)

    os.makedirs(video_output_folder, exist_ok=True)


    # ==================== 依時間點擷取 Frames ====================

    for idx, timestamp in enumerate(timestamps):
        output_file = os.path.join(video_output_folder, f"frame_{idx:04d}.png")
        is_last_frame = idx == expected_frames - 1

        if is_last_frame:
            success = extract_last_frame(video_path, output_file)

        else:
            success = extract_frame_at_timestamp(video_path, timestamp, output_file)

        if not success:
            logging.warning(
                f"{video_name}: failed to extract "
                f"frame {idx:04d} at {timestamp:.6f}s"
            )


    # ==================== 確認輸出結果 ====================

    extracted = glob.glob(os.path.join(video_output_folder, "frame_*.png"))
    extracted = [path for path in extracted if os.path.getsize(path) > 0]

    if len(extracted) == 0:
        logging.error(f"{video_name}: no frames extracted")

    elif len(extracted) != expected_frames:
        logging.warning(
            f"{video_name}: extracted "
            f"{len(extracted)}/{expected_frames} frames"
        )

    else:
        logging.info(
            f"{video_name}: extracted "
            f"{len(extracted)} PNG frames"
        )


# ==================== WebApp 單支影片處理 ====================

def main():
    """
    接收 pipeline.py 傳入的單支影片路徑，
    固定擷取 16 張 PNG Frame。
    """

    if len(sys.argv) < 2:
        logging.error("Missing video path")
        sys.exit(1)

    video_path = os.path.abspath(sys.argv[1])

    if not os.path.exists(video_path):
        logging.error(f"Video not found: {video_path}")
        sys.exit(1)

    # backend/preprocess/1.Extract_Frames.py
    #            ↓ ..
    # backend/
    base_dir = os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )

    base_dir = os.getenv("WEAVE_WORK_DIR", base_dir)

    output_folder = os.path.join(
        base_dir,
        "preprocess_output",
        "frames"
    )

    os.makedirs(
        output_folder,
        exist_ok=True
    )

    logging.info(f"Video: {video_path}")
    logging.info(f"Output: {output_folder}")
    logging.info("Frame format: PNG (lossless)")
    logging.info(
        "Frame strategy: first + "
        "14 uniformly spaced middle + last"
    )
    logging.info("Frames per video: 16")

    extract_frames_every_second(
        video_path,
        output_folder
    )

    video_name = os.path.splitext(
        os.path.basename(video_path)
    )[0]

    video_output_folder = os.path.join(
        output_folder,
        video_name
    )

    extracted = glob.glob(
        os.path.join(
            video_output_folder,
            "frame_*.png"
        )
    )

    extracted = [
        path
        for path in extracted
        if os.path.getsize(path) > 0
    ]

    if len(extracted) != 16:
        logging.error(
            f"{video_name}: expected 16 frames, "
            f"but got {len(extracted)}"
        )
        sys.exit(1)

    logging.info(
        f"Done: {video_name} "
        f"({len(extracted)} frames)"
    )


# ==================== 程式進入點 ====================

if __name__ == "__main__":
    main()