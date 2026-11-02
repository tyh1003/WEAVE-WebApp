import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
WORK = Path(os.getenv("WEAVE_WORK_DIR", "."))

from student_bot import StudentBot
from evidence import build_links
from evidence_assessment import assess_evidence


print("StudentBot Start")

bot = StudentBot(
    config_path=str(BASE / "config/student_bot_config.yaml")
)

with open(
    WORK / "output/retrieve.jsonl",
    "r",
    encoding="utf-8"
) as f:
    lines = f.readlines()

data = json.loads(lines[-1])

label, reason = bot.predict(
    Rc=data["Rc"],
    Rv=data["Rv"],
    K_int=data["K_int"],
    K_ext=data["K_ext"]
)

if isinstance(getattr(bot, "last_trace", None), dict):
    (WORK / "output/student_trace.json").write_text(json.dumps(bot.last_trace, ensure_ascii=False, indent=2), encoding="utf-8")

# Do not publish an invalid model response as a completed Student result. Keep
# the unmodified response/trace for diagnosis; never guess a label from prose.
if type(label) is not int or label not in (0, 1):
    trace = getattr(bot, "last_trace", None) or {}
    diagnostic = {"error_code": "invalid_student_output", "pred_label": label,
                  "raw_response": trace.get("raw_response", reason),
                  "trace_file": "student_trace.json", "analysis_id": data.get("analysis_id")}
    raw = diagnostic["raw_response"]
    if isinstance(raw, str):
        start, end = raw.find('{'), raw.rfind('}')
        candidate = raw[start:end+1] if 0 <= start < end else raw
        try:
            json.loads(candidate)
        except json.JSONDecodeError as error:
            diagnostic["parse_error"] = {"type": type(error).__name__, "message": str(error),
                                         "line": error.lineno, "column": error.colno, "position": error.pos}
    (WORK / "output/student_output_error.json").write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
    raise ValueError(f"Invalid Student output: pred_label={label!r}; expected integer 0 or 1. See output/student_output_error.json; no judgment was accepted.")

result = {
    "vid": data.get("vid"),
    "run_id": data.get("run_id"),
    "analysis_id": data.get("analysis_id"),
    "pred_label": label,
    "reason": reason,
    "knowledge": [],
}

try:
    result["evidence"] = build_links(data, reason)
except Exception:
    result["evidence"] = None

# Independent metadata only; no configured provider and no paid calls by default.
if result.get("evidence"):
    try:
        result["evidence"]["assessment"] = assess_evidence(result["evidence"])
    except Exception:
        result["evidence"]["assessment"] = {"status": "failed", "records": [], "failure_reason": "assessment_initialization_failed"}

with open(
    WORK / "output/final_result.json",
    "w",
    encoding="utf-8"
) as f:
    json.dump(
        result,
        f,
        ensure_ascii=False,
        indent=2
    )

print("StudentBot Done")
