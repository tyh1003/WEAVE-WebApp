import threading
from uuid import uuid4


PIPELINE_STEPS = [
    "抽取音訊與影格",
    "語音轉文字與影格壓縮",
    "OCR",
    "Data Merge",
    "Retrieve",
    "小模型分析",
    "分析完成",
]


def empty_retrieve_info():
    return {
        "vid": None,
        "Rc": None,
        "Rv": None,
        "K_int": None,
        "K_ext": None,
        "uri": [],
    }


def empty_student_prompt():
    return {
        "system_prompt": None,
        "user_prompt": None,
        "Rc": None,
        "Rv": None,
        "K_int": None,
        "K_ext": None,
    }


process_status = {
    "status": "等待上傳影片...",
    "pipeline_step": "尚未開始",
    "current_stage": "idle",
    "run_id": None,
    "pipeline_steps": PIPELINE_STEPS,
    "retrieve_input": empty_retrieve_info(),
    "student_prompt": empty_student_prompt(),
    "student_result": None,
    "error": None,
    "filename": None,
}

_status_lock = threading.RLock()
_next_run_id = 0


def reset_status(filename=None):
    global _next_run_id

    with _status_lock:
        _next_run_id += 1
        run_id = _next_run_id
        process_status.update(
            {
                "status": "影片已上傳，準備分析...",
                "pipeline_step": "尚未開始",
                "current_stage": "uploaded",
                "run_id": run_id,
                "analysis_id": str(uuid4()),
                "pipeline_steps": PIPELINE_STEPS,
                "retrieve_input": empty_retrieve_info(),
                "student_prompt": empty_student_prompt(),
                "student_result": None,
                "error": None,
                "filename": filename,
            }
        )

        return run_id


def is_current_run(run_id):
    with _status_lock:
        return run_id is None or process_status.get("run_id") == run_id


def update_status(status, pipeline_step=None, current_stage=None, error=None, run_id=None):
    with _status_lock:
        if not is_current_run(run_id):
            return False

        process_status["status"] = status

        if pipeline_step is not None:
            process_status["pipeline_step"] = pipeline_step

        if current_stage is not None:
            process_status["current_stage"] = current_stage

        process_status["error"] = error

        return True


def set_retrieve_info(data, run_id=None):
    with _status_lock:
        if not is_current_run(run_id):
            return False

        info = empty_retrieve_info()
        info.update(
            {
                "vid": data.get("vid"),
                "Rc": data.get("Rc"),
                "Rv": data.get("Rv"),
                "K_int": data.get("K_int"),
                "K_ext": data.get("K_ext"),
                "uri": data.get("uri") or data.get("url") or data.get("urls") or [],
                "not_found": data.get("not_found", False),
                "run_id": data.get("run_id"),
                "analysis_id": data.get("analysis_id"),
                "evidence": data.get("evidence"),
            }
        )
        process_status["retrieve_input"] = info

        return True


def set_student_prompt(data, run_id=None):
    with _status_lock:
        if not is_current_run(run_id):
            return False

        prompt = empty_student_prompt()
        prompt.update(data)
        process_status["student_prompt"] = prompt

        return True


def set_student_result(data, run_id=None):
    with _status_lock:
        if not is_current_run(run_id):
            return False

        process_status["student_result"] = data

        return True
