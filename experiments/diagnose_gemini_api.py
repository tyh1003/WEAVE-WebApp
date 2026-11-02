"""Manual A-D diagnostic. No pipeline imports, research writes, or automatic retries.

Run with --live to explicitly authorize up to four model requests (charges may apply).
Only sanitized configuration/status/errors are printed; generated content is discarded.
"""
import argparse
import ast
import json
import logging
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
MODEL = "gemma-4-31b-it"
HOST = "generativelanguage.googleapis.com"
API_PATH = f"/v1beta/models/{MODEL}:generateContent"
DEFAULT_IMAGE = ROOT / (
    "backend/research_data/jobs/7ba52dc729254d578d57fb60ff6dbbf9/"
    "preprocess_output/frames/7c3d6de2499643d4944e7a2c50408a20/frame_0000.png"
)


def emit(value):
    print(json.dumps(value, ensure_ascii=True), flush=True)


def system_instruction():
    # Importing Retrieve would load credentials and create output directories.
    tree = ast.parse((ROOT / "backend/Retrieve.py").read_text(encoding="utf-8-sig"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("MODEL_NAME", "SYSTEM_PROMPT"):
                    values[target.id] = ast.literal_eval(node.value)
    if values.get("MODEL_NAME") != MODEL or not isinstance(values.get("SYSTEM_PROMPT"), str):
        raise ValueError("Retrieve configuration changed; review this diagnostic before use")
    return values["SYSTEM_PROMPT"]


def ca_bundle():
    # Reuse the runner's Windows/certifi trust setup without importing pipeline.
    tree = ast.parse((ROOT / "backend/pipeline.py").read_text(encoding="utf-8-sig"))
    helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == "create_retrieve_ca_bundle")
    namespace = {"os": os}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), "<CA helper>", "exec"), namespace)
    return namespace["create_retrieve_ca_bundle"]()


def failure_category(error, code):
    if code in (401, 403):
        return "authentication_or_permission_error"
    if code == 400:
        return "http_400_invalid_request"  # Does not identify the rejected field.
    if code == 404:
        return "model_or_endpoint_not_found"
    if code == 429:
        return "quota_or_rate_limit"
    if isinstance(code, int):
        return "provider_http_error"
    chain, seen = error, set()
    while chain is not None and id(chain) not in seen:
        seen.add(id(chain))
        if isinstance(chain, socket.gaierror):
            return "dns_error"
        chain = chain.__cause__ or chain.__context__
    message = str(error).lower()
    if "getaddrinfo" in message or "name resolution" in message:
        return "dns_error"
    if "timeout" in type(error).__name__.lower():
        return "timeout"
    if "connect" in type(error).__name__.lower():
        return "network_or_tls_error"
    return "local_sdk_or_configuration_error"


def run(args):
    import httpx
    from dotenv import load_dotenv
    from google import genai
    from google.genai import types
    from PIL import Image
    import io

    sys.path.insert(0, str(ROOT / "backend"))
    from retrieve_diagnostics import sanitize

    logging.disable(logging.CRITICAL)  # Do not let dependency logs reveal payloads.
    load_dotenv(ROOT / ".env", override=False)
    key = os.getenv("GEMINI_API_KEY")  # Same explicit credential as Retrieve.
    if not key:
        raise ValueError("GEMINI_API_KEY is unavailable; no request sent")
    if any(os.getenv(k, "").lower() in ("true", "1") for k in
           ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_ENTERPRISE")):
        raise ValueError("Vertex/Enterprise override present; expected Developer API")
    custom = os.getenv("GOOGLE_GEMINI_BASE_URL", "").rstrip("/")
    if custom and custom != f"https://{HOST}":
        raise ValueError("Custom endpoint override present; review before testing")
    instruction = system_instruction()
    image = args.image.read_bytes()
    if len(image) > 5_000_000:
        raise ValueError("Diagnostic image exceeds 5 MB; choose one small saved PNG")
    with Image.open(io.BytesIO(image)) as im:
        if im.format != "PNG":
            raise ValueError("Diagnostic image must be a saved PNG")
        im.verify()
    prompt = "Briefly describe Minecraft. If an image is provided, briefly describe it too."
    clean = lambda text: sanitize(text, (key,), (instruction, prompt))
    bundle, disposable = ca_bundle()
    counts, statuses = {}, []
    current = ""

    class BudgetTransport(httpx.BaseTransport):
        def __init__(self):
            self.inner = httpx.HTTPTransport(verify=bundle, retries=0)

        def handle_request(self, request):
            if (request.method != "POST" or request.url.scheme != "https" or
                    request.url.host != HOST or request.url.path != API_PATH):
                raise ValueError("Unapproved endpoint or method blocked")
            if counts.get(current, 0) or sum(counts.values()) >= 4:
                raise ValueError("Additional request blocked; no retries allowed")
            counts[current] = 1
            response = self.inner.handle_request(request)
            statuses.append(response.status_code)
            return response

        def close(self):
            self.inner.close()

    try:
        with httpx.Client(transport=BudgetTransport(), follow_redirects=False,
                          timeout=httpx.Timeout(args.timeout, connect=10), trust_env=False) as transport:
            with genai.Client(api_key=key, vertexai=False, http_options=types.HttpOptions(
                api_version="v1beta", base_url=f"https://{HOST}", httpx_client=transport,
                timeout=args.timeout * 1000, retry_options=types.HttpRetryOptions(attempts=1)
            )) as client:
                for name, search, use_image in [("A", False, False), ("B", True, False),
                                                ("C", False, True), ("D", True, True)]:
                    current = name
                    statuses.clear()
                    record = dict(test=name, model=MODEL, endpoint=f"https://{HOST}{API_PATH}",
                                  temperature=0.0, existing_system_instruction=True,
                                  google_search=search, image_count=int(use_image))
                    emit({**record, "status": "starting"})
                    config = dict(temperature=0.0, system_instruction=instruction)
                    if search:
                        config["tools"] = [{"google_search": {}}]
                    contents = ([types.Part.from_bytes(data=image, mime_type="image/png")]
                                if use_image else []) + [prompt]
                    try:
                        client.models.generate_content(model=MODEL, contents=contents,
                                                       config=types.GenerateContentConfig(**config))
                        emit({**record, "http_status": statuses[-1] if statuses else None,
                              "success": True})
                    except Exception as error:
                        code = statuses[-1] if statuses else getattr(error, "code", None)
                        if not isinstance(code, int):
                            code = None
                        emit({**record, "http_status": code, "success": False,
                              "category": failure_category(error, code),
                              "exception": type(error).__name__,
                              "api_status": clean(getattr(error, "status", "") or ""),
                              "error": clean(getattr(error, "message", None) or str(error))})
                        return 1  # Stop even for DNS, timeout or SDK failure.
                emit({"status": "all_four_succeeded", "next_step":
                      "Investigate larger production input or untested runtime conditions; do not automatically send 16 images"})
                return 0
    finally:
        if disposable:
            Path(bundle).unlink(missing_ok=True)
        emit({"transport_attempts": sum(counts.values()), "automatic_retries": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Authorize up to 4 billable API requests")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE, help="One existing PNG for C/D")
    parser.add_argument("--timeout", type=int, default=30, choices=range(5, 61), metavar="5..60",
                        help="HTTP operation timeout in seconds (default 30)")
    args = parser.parse_args()
    if not args.live:
        emit({"status": "not_run", "message": "Add --live to authorize up to four requests; charges may apply"})
        return 0
    try:
        return run(args)
    except Exception as error:
        # Setup failures could include sensitive paths/values: never print str(error).
        emit({"status": "setup_failed", "exception": type(error).__name__,
              "message": "Check installed dependencies, credential availability, endpoint overrides and saved PNG; no automatic retry"})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
