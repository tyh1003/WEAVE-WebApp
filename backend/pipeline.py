import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from status_store import (
    process_status,
    is_current_run,
    set_retrieve_info,
    set_student_prompt,
    set_student_result,
    update_status,
)


# ============================================================
# Paths
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_DIR = os.path.join(
    BASE_DIR,
    "output"
)

PREPROCESS_OUTPUT_DIR = os.path.join(
    BASE_DIR,
    "preprocess_output"
)

ALL_JSON_PATH = os.path.join(
    PREPROCESS_OUTPUT_DIR,
    "all.json"
)

RETRIEVE_PATH = os.path.join(
    OUTPUT_DIR,
    "retrieve.jsonl"
)

RETRIEVE_DEBUG_PATH = os.path.join(
    OUTPUT_DIR,
    "retrieve_debug.jsonl"
)

RETRIEVE_FAILED_PATH = os.path.join(
    OUTPUT_DIR,
    "retrieve_failed.jsonl"
)

PYTHON_EXECUTABLE = sys.executable


# ============================================================
# Retrieve CA Bundle
# ============================================================

def create_retrieve_ca_bundle():
    import certifi
    import ssl
    import tempfile

    enum_certificates = getattr(
        ssl,
        "enum_certificates",
        None
    )

    if enum_certificates is None:
        return certifi.where(), False

    system_certificates = []
    seen_certificates = set()

    for store_name in ("ROOT", "CA"):

        try:
            certificates = enum_certificates(
                store_name
            )

        except OSError:
            continue

        for certificate, encoding, _trust in certificates:

            if (
                encoding != "x509_asn"
                or certificate in seen_certificates
            ):
                continue

            seen_certificates.add(
                certificate
            )

            system_certificates.append(
                certificate
            )

    if not system_certificates:
        return certifi.where(), False

    file_descriptor, bundle_path = tempfile.mkstemp(
        prefix="retrieve-ca-",
        suffix=".pem",
    )

    with os.fdopen(
        file_descriptor,
        "wb"
    ) as bundle:

        with open(
            certifi.where(),
            "rb"
        ) as certifi_bundle:

            bundle.write(
                certifi_bundle.read()
            )

        bundle.write(b"\n")

        for certificate in system_certificates:

            pem_certificate = (
                ssl.DER_cert_to_PEM_cert(
                    certificate
                )
            )

            bundle.write(
                pem_certificate.encode(
                    "ascii"
                )
            )

    return bundle_path, True


# ============================================================
# Run subprocess
# ============================================================

def run_command(args, check=True, evidence_context=None):

    env = os.environ.copy()
    if evidence_context:
        env["WEAVE_RUN_ID"] = str(evidence_context[0])
        env["WEAVE_ANALYSIS_ID"] = evidence_context[1]

    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    # HuggingFace 模型使用本機 Cache。
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["HF_HUB_OFFLINE"] = "1"

    temporary_ca_bundle = None


    # Retrieve.py 需要網路 SSL Certificate。
    if any(
        str(arg).endswith("Retrieve.py")
        for arg in args
    ):

        try:

            ca_bundle, is_temporary = (
                create_retrieve_ca_bundle()
            )

            env["SSL_CERT_FILE"] = ca_bundle
            env["REQUESTS_CA_BUNDLE"] = ca_bundle
            env["CURL_CA_BUNDLE"] = ca_bundle
            env[
                "GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"
            ] = ca_bundle

            if is_temporary:
                temporary_ca_bundle = ca_bundle

        except Exception:
            pass


    try:

        result = subprocess.run(
            args,
            cwd=BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="ignore",
        )

        print("\n" + "=" * 80)
        print("[SUBPROCESS]")
        print("Python:", PYTHON_EXECUTABLE)
        print("Command:", args)
        print("CWD:", BASE_DIR)
        print("Return code:", result.returncode)

        if result.stdout:
            print("\n[STDOUT]")
            print(result.stdout)

        if result.stderr:
            print("\n[STDERR]")
            print(result.stderr)

        print("=" * 80 + "\n")

        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                args,
                output=result.stdout,
                stderr=result.stderr,
            )

        return result

    finally:


        if temporary_ca_bundle:

            try:
                os.remove(
                    temporary_ca_bundle
                )

            except OSError:
                pass


# ============================================================
# JSON Utils
# ============================================================

def read_latest_jsonl(path):

    if not os.path.exists(path):
        return None

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:

        lines = [
            line.strip()
            for line in f
            if line.strip()
        ]

    if not lines:
        return None

    return json.loads(
        lines[-1]
    )


def read_json_if_exists(path):

    if not os.path.exists(path):
        return None

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


# ============================================================
# Runtime Cleanup
# ============================================================

def safe_remove_path(path):

    abs_path = os.path.abspath(path)
    base_path = os.path.abspath(BASE_DIR)

    if (
        abs_path == base_path
        or not abs_path.startswith(
            base_path + os.sep
        )
    ):
        return

    if os.path.isdir(abs_path):

        shutil.rmtree(
            abs_path
        )

    elif os.path.exists(abs_path):

        os.remove(
            abs_path
        )


def video_id_from_path(video_path):

    return os.path.splitext(
        os.path.basename(
            video_path
        )
    )[0]


def clear_runtime_outputs(video_path):

    video_id = video_id_from_path(
        video_path
    )

    paths = [

        # =========================
        # Merge
        # =========================

        ALL_JSON_PATH,


        # =========================
        # Retrieve
        # =========================

        RETRIEVE_PATH,
        RETRIEVE_DEBUG_PATH,
        RETRIEVE_FAILED_PATH,


        # =========================
        # Student
        # =========================

        os.path.join(
            OUTPUT_DIR,
            "final_result.json"
        ),

        os.path.join(
            OUTPUT_DIR,
            "student_result.json"
        ),


        # =========================
        # Audio
        # =========================

        os.path.join(
            PREPROCESS_OUTPUT_DIR,
            "audio",
            f"{video_id}.wav"
        ),


        # =========================
        # Transcript
        # =========================

        os.path.join(
            PREPROCESS_OUTPUT_DIR,
            "transcript",
            f"{video_id}.json"
        ),


        # =========================
        # Frames
        # =========================

        os.path.join(
            PREPROCESS_OUTPUT_DIR,
            "frames",
            video_id
        ),


        # =========================
        # VLM
        # =========================

        os.path.join(
            PREPROCESS_OUTPUT_DIR,
            "vlm",
            f"{video_id}.json"
        ),

        os.path.join(
            PREPROCESS_OUTPUT_DIR,
            "vlm_raw",
            f"{video_id}.json"
        ),
    ]

    for path in paths:

        try:
            safe_remove_path(
                path
            )

        except OSError:
            pass


# ============================================================
# Validation
# ============================================================

def data_matches_video(
    video_path,
    data
):

    return (
        bool(data)
        and str(
            data.get(
                "vid",
                ""
            )
        )
        == video_id_from_path(
            video_path
        )
    )


def file_was_written_after(
    path,
    started_at
):

    return (
        os.path.exists(path)
        and os.path.getmtime(path)
        >= started_at - 1
    )


def merged_data_is_valid(
    video_path,
    data
):

    if not data_matches_video(
        video_path,
        data
    ):
        return False

    required_fields = {
        "vid",
        "transcript",
        "description",
    }

    return required_fields.issubset(
        data.keys()
    )


# ============================================================
# Retrieve Utils
# ============================================================

def retrieve_result_is_current(
    video_path,
    retrieve_data,
    started_at
):

    if (
        not retrieve_data
        or not file_was_written_after(
            RETRIEVE_PATH,
            started_at
        )
    ):
        return False

    if not data_matches_video(
        video_path,
        retrieve_data
    ):
        return False

    return True


def retrieve_failure_message(
    video_path,
    started_at
):

    failed_data = read_latest_jsonl(
        RETRIEVE_FAILED_PATH
    )

    failed_is_current = (
        file_was_written_after(
            RETRIEVE_FAILED_PATH,
            started_at
        )
    )

    if (
        failed_is_current
        and failed_data
        and str(
            failed_data.get(
                "vid",
                ""
            )
        )
        == video_id_from_path(
            video_path
        )
    ):

        reason = str(
            failed_data.get(
                "reason",
                ""
            )
        ).strip()

        if reason:
            return (
                f"Retrieve 失敗："
                f"{reason[:300]}"
            )

    return (
        "Retrieve 未產生目前影片的 "
        "retrieve.jsonl"
    )


def retrieve_not_found_payload(
    video_path
):

    return {
        "vid": video_id_from_path(
            video_path
        ),
        "Rc": "未查到",
        "Rv": "未查到",
        "K_int": "未查到",
        "K_ext": "未查到",
        "uri": [],
        "not_found": True,
    }


# ============================================================
# Student Utils
# ============================================================

def display_value(value):

    if (
        value is None
        or value == ""
    ):
        return "尚未產生"

    if isinstance(
        value,
        list
    ):

        if not value:
            return "尚未產生"

        return "\n".join(
            [
                f"- {item}"
                for item in value
            ]
        )

    return str(value)


def load_student_system_prompt():

    config_path = os.path.join(
        BASE_DIR,
        "config",
        "student_bot_config.yaml"
    )

    try:

        import yaml

        with open(
            config_path,
            "r",
            encoding="utf-8"
        ) as f:

            config = (
                yaml.safe_load(f)
                or {}
            )

        return (
            config.get(
                "system_prompt"
            )
            or "尚未產生"
        )

    except Exception:

        return "尚未產生"


def build_student_prompt_payload(
    retrieve_data
):

    rc = retrieve_data.get(
        "Rc"
    )

    rv = retrieve_data.get(
        "Rv"
    )

    k_int = retrieve_data.get(
        "K_int"
    )

    k_ext = retrieve_data.get(
        "K_ext"
    )

    user_prompt = f"""
請根據以下資料判斷影片內容為真或假，並輸出 pred_label 與 reason。

Rc:
{display_value(rc)}

Rv:
{display_value(rv)}

K_int:
{display_value(k_int)}

K_ext:
{display_value(k_ext)}
    """.strip()

    return {
        "system_prompt":
            load_student_system_prompt(),

        "user_prompt":
            user_prompt,

        "Rc":
            rc,

        "Rv":
            rv,

        "K_int":
            k_int,

        "K_ext":
            k_ext,
    }


def load_student_result():

    for filename in (
        "student_result.json",
        "final_result.json"
    ):

        data = read_json_if_exists(
            os.path.join(
                OUTPUT_DIR,
                filename
            )
        )

        if data is not None:
            return data

    return None


# ============================================================
# Error Handling
# ============================================================

def fail_pipeline(
    step,
    message,
    run_id=None
):

    update_status(
        message,
        step,
        "error",
        message,
        run_id=run_id
    )


def format_process_error(error):

    cmd = (
        error.cmd
        if isinstance(
            error.cmd,
            list
        )
        else [
            str(error.cmd)
        ]
    )

    script = next(
        (
            item
            for item in cmd
            if str(item).endswith(
                ".py"
            )
        ),
        cmd[0]
        if cmd
        else "subprocess",
    )

    return (
        f"{script} 執行失敗 "
        f"(code {error.returncode})"
    )


# ============================================================
# Main Pipeline
# ============================================================

def run_pipeline(
    video_path,
    run_id=None
):

    try:

        # ====================================================
        # Check Current Run
        # ====================================================

        if not is_current_run(
            run_id
        ):
            return


        # ====================================================
        # Cleanup
        # ====================================================

        clear_runtime_outputs(
            video_path
        )


        # ====================================================
        # Stage 1
        #
        # Video2Wav
        # Extract Frames
        # VLM
        #
        # 三個工作平行執行。
        # ====================================================

        if not update_status(
            "正在進行音訊、影格與視覺內容分析...",
            "音訊、影格與視覺內容分析",
            "preprocess",
            run_id=run_id,
        ):
            return


        with ThreadPoolExecutor(
            max_workers=3
        ) as executor:

            future_audio = (
                executor.submit(
                    run_command,
                    [
                        PYTHON_EXECUTABLE,
                        "preprocess/1.Video2Wav.py",
                        video_path
                    ],
                )
            )

            future_frames = (
                executor.submit(
                    run_command,
                    [
                        PYTHON_EXECUTABLE,
                        "preprocess/1.Extract_Frames.py",
                        video_path
                    ],
                )
            )

            future_vlm = (
                executor.submit(
                    run_command,
                    [
                        PYTHON_EXECUTABLE,
                        "preprocess/1.VLM.py",
                        video_path
                    ],
                )
            )


            # ================================================
            # Barrier
            #
            # 三個 Stage 1 工作全部完成後才進入 Stage 2。
            # ================================================

            future_audio.result()
            future_frames.result()
            future_vlm.result()


        if not is_current_run(
            run_id
        ):
            return


        # ====================================================
        # Stage 2
        #
        # Whisper Speech-to-Text
        # ====================================================

        if not update_status(
            "正在進行語音轉文字...",
            "語音轉文字",
            "preprocess",
            run_id=run_id,
        ):
            return


        run_command(
            [
                PYTHON_EXECUTABLE,
                "preprocess/2.Wav2Transcript.py",
                video_path
            ]
        )


        if not is_current_run(
            run_id
        ):
            return


        # ====================================================
        # Data Merge
        #
        # transcript + VLM description
        # ====================================================

        if not update_status(
            "正在整合多模態資料...",
            "Data Merge",
            "preprocess",
            run_id=run_id,
        ):
            return


        data_merge_started_at = (
            time.time()
        )


        run_command(
            [
                PYTHON_EXECUTABLE,
                "preprocess/4.Data_Merge.py",
                video_path
            ]
        )


        if not is_current_run(
            run_id
        ):
            return


        # ====================================================
        # Validate all.json
        # ====================================================

        merged_data = (
            read_json_if_exists(
                ALL_JSON_PATH
            )
        )


        print(
            "\n===== DATA MERGE DEBUG ====="
        )

        print(
            "ALL_JSON_PATH:",
            ALL_JSON_PATH
        )

        print(
            "exists:",
            os.path.exists(
                ALL_JSON_PATH
            )
        )


        if os.path.exists(
            ALL_JSON_PATH
        ):

            print(
                "all.json mtime:",
                os.path.getmtime(
                    ALL_JSON_PATH
                )
            )


        print(
            "data_merge_started_at:",
            data_merge_started_at
        )

        print(
            "mtime check:",
            file_was_written_after(
                ALL_JSON_PATH,
                data_merge_started_at
            )
        )

        print(
            "video_path:",
            video_path
        )

        print(
            "expected vid:",
            repr(
                video_id_from_path(
                    video_path
                )
            )
        )

        print(
            "actual vid:",
            repr(
                merged_data.get(
                    "vid"
                )
            )
            if merged_data
            else None
        )

        print(
            "vid check:",
            data_matches_video(
                video_path,
                merged_data
            )
        )

        print(
            "required fields check:",
            merged_data_is_valid(
                video_path,
                merged_data
            )
        )

        print(
            "merged_data:",
            merged_data
        )

        print(
            "============================\n"
        )


        if (
            not file_was_written_after(
                ALL_JSON_PATH,
                data_merge_started_at
            )
            or not merged_data_is_valid(
                video_path,
                merged_data
            )
        ):

            fail_pipeline(
                "Data Merge",
                (
                    "all.json 未產生目前影片"
                    "的完整資料"
                ),
                run_id=run_id
            )

            return


        # ====================================================
        # Retrieve
        # ====================================================

        if not update_status(
            "正在進行知識檢索與外部證據搜尋...",
            "Retrieve",
            "retrieve",
            run_id=run_id,
        ):
            return


        retrieve_started_at = (
            time.time()
        )


        retrieve_process = run_command(
            [
                PYTHON_EXECUTABLE,
                "Retrieve.py"
            ],
            check=False,
            evidence_context=(run_id, process_status.get("analysis_id")) if run_id is not None else None
        )


        if not is_current_run(
            run_id
        ):
            return


        if (
            retrieve_process.returncode
            != 0
        ):

            fail_pipeline(
                "Retrieve",
                (
                    "Retrieve 執行失敗 "
                    f"(code "
                    f"{retrieve_process.returncode})"
                ),
                run_id=run_id,
            )

            return


        # ====================================================
        # Validate Retrieve
        # ====================================================

        retrieve_data = (
            read_latest_jsonl(
                RETRIEVE_PATH
            )
        )


        if not retrieve_result_is_current(
            video_path,
            retrieve_data,
            retrieve_started_at
        ):

            set_retrieve_info(
                retrieve_not_found_payload(
                    video_path
                ),
                run_id=run_id
            )

            fail_pipeline(
                "Retrieve",
                "未查到",
                run_id=run_id
            )

            return


        # ====================================================
        # Store Retrieve Result
        # ====================================================

        set_retrieve_info(
            retrieve_data,
            run_id=run_id
        )


        # ====================================================
        # Build Student Prompt
        # ====================================================

        set_student_prompt(
            build_student_prompt_payload(
                retrieve_data
            ),
            run_id=run_id
        )


        # ====================================================
        # Student
        # ====================================================

        if not update_status(
            "正在進行 Student Model 分析...",
            "Student Model",
            "student",
            run_id=run_id,
        ):
            return


        run_command(
            [
                PYTHON_EXECUTABLE,
                "run_student.py"
            ]
        )


        if not is_current_run(
            run_id
        ):
            return


        # ====================================================
        # Student Result
        # ====================================================

        student_result = (
            load_student_result()
        )


        if student_result:

            set_student_result(
                student_result,
                run_id=run_id
            )


        # ====================================================
        # Done
        # ====================================================

        update_status(
            "分析完成",
            "分析完成",
            "done",
            run_id=run_id
        )


    # ========================================================
    # Subprocess Error
    # ========================================================

    except subprocess.CalledProcessError as error:

        fail_pipeline(
            "分析失敗",
            format_process_error(
                error
            ),
            run_id=run_id
        )


    # ========================================================
    # Unexpected Error
    # ========================================================

    except Exception as error:

        print(
            "Pipeline unexpected error:",
            repr(error)
        )

        fail_pipeline(
            "分析失敗",
            "分析流程發生錯誤",
            run_id=run_id
        )
