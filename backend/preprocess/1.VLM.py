import tempfile
import os
import sys

os.environ["FORCE_QWENVL_VIDEO_READER"] = "torchcodec"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import re
import json
import gc
import logging
import subprocess
from pathlib import Path

import torch

from transformers import AutoProcessor, BitsAndBytesConfig, Qwen3VLForConditionalGeneration
from qwen_vl_utils import process_vision_info


# ==================== 基本設定 ====================

MODEL_ID = "Qwen/Qwen3-VL-4B-Instruct"

BASE_DIR = Path(os.getenv("WEAVE_WORK_DIR", str(Path(__file__).resolve().parent.parent)))

VLM_OUTPUT_DIR = (
    BASE_DIR
    / "preprocess_output"
    / "vlm"
)

VLM_RAW_OUTPUT_DIR = (
    BASE_DIR
    / "preprocess_output"
    / "vlm_raw"
)

VLM_OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

VLM_RAW_OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

# 修復影片只會建立在系統暫存目錄，不會修改或覆寫 VIDEO_DIR 中的任何原始影片。
VIDEO_REPAIR_DIR = (
    Path(tempfile.gettempdir())
    / "exmrd_vlm_video_repair"
)




# ==================== 影片取樣設定 ====================

# 每秒取樣 Frame 數量。
VIDEO_FPS = 2

# 單支影片最多使用的 Frame 數量。
VIDEO_MAX_FRAMES = 48

# 每個 Frame 使用動態解析度，不強制固定寬高，避免橫式與直式影片變形。
# 約 131072 Pixels，作為低解析度影片的最小 Pixel Budget。
VIDEO_MIN_PIXELS = 128 * 32 * 32

# 約 230400 Pixels，接近原本 480 x 480 的 Pixel Budget。
VIDEO_MAX_PIXELS = 480 * 480


# ==================== 模型生成設定 ====================

# 模型單次最多產生的輸出 Token 數量。
OUTPUT_MAX_NEW_TOKENS = 2000

# 輕微降低重複生成，但避免過度懲罰正常的實體名稱與中文句型重複。
REPETITION_PENALTY = 1.1


# ==================== Logging 設定 ====================

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ==================== 影片分析 Prompt ====================

VIDEO_ANALYSIS_PROMPT = """
Objectively describe the visual content of the video in temporal order. Respond in Traditional Chinese.
"""


# ==================== 顯示 GPU VRAM 狀態 ====================

def show_gpu_memory():
    """顯示目前 GPU 的總 VRAM、已使用 VRAM 與剩餘 VRAM。"""

    if not torch.cuda.is_available():
        logging.warning("目前未偵測到 CUDA GPU。")
        return

    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True, check=True)
        gpu_info = result.stdout.strip()

        if gpu_info:
            logging.info("GPU VRAM 狀態 [名稱, Total MB, Used MB, Free MB]: %s", gpu_info)

    except Exception as error:
        logging.warning("無法取得 nvidia-smi GPU 資訊: %s", error)


# ==================== 清理啟動前 GPU Cache ====================

def cleanup_gpu_cache():
    """清除目前 Python Process 中已經失去引用的 CPU 與 GPU 暫存記憶體。"""

    gc.collect()

    if torch.cuda.is_available():
        try:
            torch.cuda.synchronize()
        except Exception:
            pass

        torch.cuda.empty_cache()

        try:
            torch.cuda.ipc_collect()
        except Exception:
            pass


# ==================== 清理單支影片 Cache ====================

def cleanup_video_cache():
    """清除單支影片完成後已經失去引用的暫存記憶體，不會刪除 model 與 processor。"""

    gc.collect()

    if torch.cuda.is_available():
        torch.cuda.empty_cache()


# ==================== 模型釋放後清理 GPU ====================

def cleanup_after_model_release():
    """model 與 processor 已由主程式刪除後，清除剩餘 CPU 與 GPU Cache。"""

    gc.collect()

    if torch.cuda.is_available():
        try:
            torch.cuda.synchronize()
        except Exception:
            pass

        torch.cuda.empty_cache()

        try:
            torch.cuda.ipc_collect()
        except Exception:
            pass

        gc.collect()
        torch.cuda.empty_cache()

    show_gpu_memory()


# ==================== 清理單行文字 ====================

def clean_single_line_text(text):
    """將模型輸出整理為單行，移除換行、Tab 與連續空白。"""

    if not text:
        return ""

    return re.sub(r"\s+", " ", text).strip()


# ==================== 計算文字 Token 數 ====================

def count_text_tokens(text, processor):
    """使用 Qwen3-VL Tokenizer 計算文字 Token 數量。"""

    if not text:
        return 0

    return len(processor.tokenizer.encode(text, add_special_tokens=False))


# ==================== 載入 Qwen3-VL-4B ====================

def load_model():
    """使用 BitsAndBytes 4-bit NF4 量化載入 Qwen3-VL-4B-Instruct。"""

    if not torch.cuda.is_available():
        raise RuntimeError("目前沒有偵測到 CUDA GPU，請確認 NVIDIA Driver、CUDA 與 PyTorch CUDA 環境是否正常。")

    gpu_name = torch.cuda.get_device_name(0)
    gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
    gpu_capability = torch.cuda.get_device_capability(0)

    logging.info("GPU: %s", gpu_name)
    logging.info("GPU VRAM: %.2f GB", gpu_memory)
    logging.info("GPU Compute Capability: %s", gpu_capability)
    logging.info("PyTorch: %s", torch.__version__)
    logging.info("PyTorch CUDA: %s", torch.version.cuda)
    logging.info("載入模型: %s", MODEL_ID)

    quantization_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.float16)

    model = Qwen3VLForConditionalGeneration.from_pretrained(MODEL_ID, quantization_config=quantization_config, device_map="auto", dtype=torch.float16, low_cpu_mem_usage=True)
    processor = AutoProcessor.from_pretrained(MODEL_ID)

    model.eval()

    logging.info("模型載入完成。")
    show_gpu_memory()

    return model, processor


# ==================== 建立影片輸入 Message ====================

def build_video_messages(video_path):
    """建立 Qwen3-VL 使用的影片與 Prompt Message，使用動態解析度保留影片原始寬高比。"""

    video_path_str = str(video_path.resolve())

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "video",
                    "video": video_path_str,
                    "fps": VIDEO_FPS,
                    "max_frames": VIDEO_MAX_FRAMES,
                    "min_pixels": VIDEO_MIN_PIXELS,
                    "max_pixels": VIDEO_MAX_PIXELS
                },
                {
                    "type": "text",
                    "text": VIDEO_ANALYSIS_PROMPT
                }
            ]
        }
    ]

    return messages


# ==================== 刪除暫存修復影片 ====================

def remove_repaired_video(repaired_path):
    """刪除 FFmpeg 建立的暫存修復影片，不會操作任何原始影片。"""

    if repaired_path is None:
        return

    try:
        if repaired_path.exists():
            repaired_path.unlink()
            logging.info("已刪除暫存修復影片: %s", repaired_path)

    except Exception as error:
        logging.warning("無法刪除暫存修復影片 %s: %s", repaired_path, error)


# ==================== 使用 FFmpeg 修復影片 ====================

def repair_video_with_ffmpeg(video_path):
    """將無法正常解碼的影片複製至獨立暫存目錄重新編碼，不會修改原始影片。"""

    VIDEO_REPAIR_DIR.mkdir(parents=True, exist_ok=True)

    repaired_path = VIDEO_REPAIR_DIR / f"{video_path.stem}_repaired.mp4"

    remove_repaired_video(repaired_path)

    command = [
        "ffmpeg",
        "-y",
        "-v", "warning",
        "-err_detect", "ignore_err",
        "-fflags", "+discardcorrupt",
        "-i", str(video_path),
        "-map", "0:v:0",
        "-an",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(repaired_path)
    ]

    logging.warning("開始建立暫存修復影片: %s", video_path.name)

    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    ffmpeg_message = result.stderr.strip()

    if ffmpeg_message:
        logging.warning("FFmpeg 修復訊息 [%s]: %s", video_path.name, ffmpeg_message)

    if result.returncode != 0:
        remove_repaired_video(repaired_path)
        raise RuntimeError(f"FFmpeg 修復失敗，Return Code: {result.returncode}")

    if not repaired_path.exists():
        raise RuntimeError("FFmpeg 修復完成後沒有產生暫存影片。")

    if repaired_path.stat().st_size <= 0:
        remove_repaired_video(repaired_path)
        raise RuntimeError("FFmpeg 修復後的暫存影片大小為 0 Bytes。")

    logging.info("FFmpeg 暫存修復完成: %s -> %s", video_path.name, repaired_path)

    return repaired_path


# ==================== 使用 Qwen Vision Reader 讀取影片 ====================

def read_video_vision_inputs(messages):
    """使用 qwen_vl_utils 將影片解碼並轉換為 Qwen3-VL 所需的視覺輸入。"""

    image_inputs, video_inputs, video_kwargs = process_vision_info(messages, image_patch_size=16, return_video_kwargs=True, return_video_metadata=True)

    return image_inputs, video_inputs, video_kwargs


# ==================== 影片視覺前處理與自動修復 ====================

def prepare_video_vision_inputs(video_path, processor):
    """優先讀取原始影片，若影片解碼失敗則建立暫存修復影片並重新讀取。"""

    messages = None
    text = None
    image_inputs = None
    video_inputs = None
    video_metadatas = None
    video_kwargs = None
    repaired_path = None
    used_repaired_video = False

    try:

        # ==================== 建立原始影片 Message ====================

        messages = build_video_messages(video_path)


        # ==================== 套用原始影片 Chat Template ====================

        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


        # ==================== 第一次讀取原始影片 ====================

        try:
            image_inputs, video_inputs, video_kwargs = read_video_vision_inputs(messages)

        except torch.cuda.OutOfMemoryError:
            raise

        except Exception as original_error:

            # ==================== 原始影片解碼失敗 ====================

            logging.warning("原始影片視覺前處理失敗: %s", video_path.name)
            logging.warning("原始影片解碼錯誤: %s", original_error)


            # ==================== 建立暫存修復影片 ====================

            repaired_path = repair_video_with_ffmpeg(video_path)


            # ==================== 建立修復影片 Message ====================

            messages = build_video_messages(repaired_path)


            # ==================== 套用修復影片 Chat Template ====================

            text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


            # ==================== 第二次讀取修復影片 ====================

            try:
                image_inputs, video_inputs, video_kwargs = read_video_vision_inputs(messages)
                used_repaired_video = True
                logging.info("暫存修復影片讀取成功: %s", video_path.name)

            except torch.cuda.OutOfMemoryError:
                raise

            except Exception as repaired_error:
                raise RuntimeError(f"原始影片與暫存修復影片皆無法完成視覺前處理。原始錯誤: {original_error} | 修復後錯誤: {repaired_error}") from repaired_error


        # ==================== 整理 Video Metadata ====================

        if video_inputs is not None:
            video_inputs, video_metadatas = zip(*video_inputs)
            video_inputs = list(video_inputs)
            video_metadatas = list(video_metadatas)


        # ==================== 回傳視覺前處理結果 ====================

        return text, image_inputs, video_inputs, video_metadatas, video_kwargs, used_repaired_video

    finally:

        # ==================== 刪除暫存修復影片 ====================

        remove_repaired_video(repaired_path)


# ==================== 分析單支影片 ====================

def analyze_video(video_path, model, processor):
    """使用 Qwen3-VL-4B 分析單支影片，影片解碼失敗時只使用暫存副本進行修復。"""

    text = None
    image_inputs = None
    video_inputs = None
    video_metadatas = None
    video_kwargs = None
    inputs = None
    generated_ids = None
    generated_ids_trimmed = None
    model_output = None
    used_repaired_video = False

    try:

        # ==================== 影片視覺前處理 ====================

        text, image_inputs, video_inputs, video_metadatas, video_kwargs, used_repaired_video = prepare_video_vision_inputs(video_path=video_path, processor=processor)


        # ==================== 建立模型輸入 Tensor ====================

        inputs = processor(text=text, images=image_inputs, videos=video_inputs, video_metadata=video_metadatas, return_tensors="pt", do_resize=False, cap_pixels_per_frame=True, **video_kwargs)
        inputs = inputs.to(model.device)


        # ==================== Input 資訊 ====================

        input_token_count = inputs.input_ids.shape[-1]
        logging.info("Input Token 數: %d", input_token_count)

        if used_repaired_video:
            logging.info("本次推論使用 FFmpeg 暫存修復後的影片 Frames: %s", video_path.name)

        if hasattr(inputs, "video_grid_thw") and inputs.video_grid_thw is not None:
            logging.info("影片 video_grid_thw: %s", inputs.video_grid_thw.tolist())

        show_gpu_memory()


        # ==================== 模型生成 ====================

        with torch.inference_mode():
            generated_ids = model.generate(**inputs, max_new_tokens=OUTPUT_MAX_NEW_TOKENS, do_sample=False, repetition_penalty=REPETITION_PENALTY, use_cache=True)


        # ==================== 移除原始 Input Token ====================

        generated_ids_trimmed = [output_ids[len(input_ids):] for input_ids, output_ids in zip(inputs.input_ids, generated_ids)]


        # ==================== Output Token 統計 ====================

        output_token_count = generated_ids_trimmed[0].numel()

        logging.info("模型實際輸出 Token 數: %d / %d", output_token_count, OUTPUT_MAX_NEW_TOKENS)

        if output_token_count >= OUTPUT_MAX_NEW_TOKENS:
            logging.warning("模型輸出已達 max_new_tokens 上限，內容可能被截斷。")
        else:
            logging.info("模型在 Token 上限前自行結束生成。")


        # ==================== Decode 原始模型輸出 ====================

        model_output = processor.batch_decode(generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]


        # ==================== 建立正式影片描述 ====================

        description = clean_single_line_text(model_output)

        if not description:
            raise RuntimeError("模型沒有產生任何影片描述。")


        # ==================== Description Token 統計 ====================

        description_token_count = count_text_tokens(description, processor)

        logging.info("RAW Model Output Token 數: %d", output_token_count)
        logging.info("Description Token 數: %d", description_token_count)


        # ==================== 回傳分析結果 ====================

        return description, model_output

    finally:

        # ==================== 刪除單支影片暫存物件 ====================

        del text
        del image_inputs
        del video_inputs
        del video_metadatas
        del video_kwargs
        del inputs
        del generated_ids
        del generated_ids_trimmed
        del model_output

        cleanup_video_cache()


# ==================== 清理影片修復暫存資料夾 ====================

def cleanup_video_repair_directory():
    """移除程式建立且目前為空的影片修復暫存資料夾，不會操作原始影片目錄。"""

    try:
        if VIDEO_REPAIR_DIR.exists() and not any(VIDEO_REPAIR_DIR.iterdir()):
            VIDEO_REPAIR_DIR.rmdir()
            logging.info("已移除空的影片修復暫存資料夾: %s", VIDEO_REPAIR_DIR)

    except Exception as error:
        logging.warning("無法移除影片修復暫存資料夾 %s: %s", VIDEO_REPAIR_DIR, error)


# ==================== 主程式 ====================

def main():
    """
    接收 pipeline.py 傳入的單支影片，
    使用 Qwen3-VL-4B 產生影片視覺描述。
    """

    # ==================== 取得影片 ====================

    if len(sys.argv) < 2:
        logging.error("Missing video path")
        sys.exit(1)

    video_path = Path(
        sys.argv[1]
    ).resolve()

    if not video_path.exists():
        logging.error(
            "Video not found: %s",
            video_path
        )
        sys.exit(1)

    vid = video_path.stem


    # ==================== 輸出路徑 ====================

    output_path = (
        VLM_OUTPUT_DIR
        / f"{vid}.json"
    )

    raw_output_path = (
        VLM_RAW_OUTPUT_DIR
        / f"{vid}.json"
    )


    # ==================== 初始化 ====================

    cleanup_gpu_cache()


    # ==================== 驗證設定 ====================

    if VIDEO_MIN_PIXELS <= 0:
        raise ValueError(
            "VIDEO_MIN_PIXELS 必須大於 0。"
        )

    if VIDEO_MAX_PIXELS <= VIDEO_MIN_PIXELS:
        raise ValueError(
            "VIDEO_MAX_PIXELS 必須大於 VIDEO_MIN_PIXELS。"
        )


    # ==================== 顯示設定 ====================

    logging.info("=" * 50)
    logging.info("Qwen3-VL Video Analysis")
    logging.info("模型: %s", MODEL_ID)
    logging.info("影片: %s", video_path)
    logging.info("VID: %s", vid)
    logging.info("影像取樣 FPS: %.2f", VIDEO_FPS)
    logging.info(
        "最大 Frame 數: %d",
        VIDEO_MAX_FRAMES
    )
    logging.info(
        "最大輸出 Token: %d",
        OUTPUT_MAX_NEW_TOKENS
    )
    logging.info("=" * 50)


    # ==================== 載入模型 ====================

    model = None
    processor = None

    try:

        model, processor = load_model()


        # ==================== 分析影片 ====================

        logging.info(
            "開始分析影片: %s",
            video_path.name
        )

        description, model_output = analyze_video(
            video_path=video_path,
            model=model,
            processor=processor
        )


        # ==================== 正式結果 ====================

        result = {
            "vid": vid,
            "description": description
        }

        with open(
            output_path,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                result,
                f,
                ensure_ascii=False,
                indent=2
            )


        # ==================== RAW 結果 ====================

        raw_result = {
            "vid": vid,
            "model_output": model_output
        }

        with open(
            raw_output_path,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                raw_result,
                f,
                ensure_ascii=False,
                indent=2
            )


        # ==================== 完成 ====================

        logging.info(
            "VLM Done: %s",
            vid
        )

        logging.info(
            "Description chars: %d",
            len(description)
        )

        logging.info(
            "Saved: %s",
            output_path
        )


    except torch.cuda.OutOfMemoryError:

        logging.exception(
            "GPU VRAM 不足: %s",
            video_path.name
        )

        sys.exit(1)


    except Exception:

        logging.exception(
            "VLM 處理失敗: %s",
            video_path.name
        )

        sys.exit(1)


    finally:

        # ==================== 釋放模型 ====================

        if model is not None:
            del model

        if processor is not None:
            del processor

        cleanup_after_model_release()
        cleanup_video_repair_directory()


    logging.info("=" * 50)
    logging.info("VLM complete")
    logging.info("=" * 50)

# ==================== 程式進入點 ====================

if __name__ == "__main__":
    main()