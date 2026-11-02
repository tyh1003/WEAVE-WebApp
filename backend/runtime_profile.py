"""Additive, best-effort timing. No prompts, credentials, network or inference."""
import csv
import io
import json
import os
import platform
import time
from contextlib import contextmanager
from pathlib import Path


def hardware():
    return {'os': platform.system(), 'architecture': platform.machine(),
            'processor': platform.processor() or None, 'logical_cpus': os.cpu_count(),
            'gpu': None, 'gpu_note': 'GPU model/utilization not instrumented'}


def usage(response):
    raw = response.get('usage_metadata', {}) if isinstance(response, dict) else getattr(response, 'usage_metadata', None)
    if hasattr(raw, 'model_dump'):
        raw = raw.model_dump()
    raw = raw if isinstance(raw, dict) else {}
    return {key: raw[key] for key in ('prompt_token_count', 'candidates_token_count', 'total_token_count', 'thoughts_token_count')
            if isinstance(raw.get(key), int)}


def new_profile():
    return {'schema_version': 1, 'hardware': hardware(), 'stages': [],
            'estimated_api_cost': None, 'cost_note': 'No validated pricing schedule; cost not estimated',
            'external_api_coverage': 'Retrieve Gemini SDK and separate automatic summaries; other providers and display translations not instrumented',
            'call_count_scope': 'SDK invocations; transport-level retries are not observable'}


@contextmanager
def observe_gemini(workspace):
    """Observe existing SDK calls without changing their arguments or return values."""
    from google.genai.models import Models
    originals = {}
    path = Path(workspace) / 'output/runtime_calls.jsonl'
    def append(row):
        try:
            with path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(row) + '\n')
        except OSError:
            pass
    def wrap(name, original):
        def observed(self, *args, **kwargs):
            started = time.perf_counter()
            # Start record survives a process failure; no request contents are logged.
            append({'event': 'started', 'method': name})
            row = {'event': 'finished', 'method': name, 'status': 'failed', 'token_usage': {}}
            try:
                result = original(self, *args, **kwargs)
                row['status'] = 'succeeded'
                try:
                    row['token_usage'] = usage(result)
                except Exception:
                    pass  # Telemetry must never replace the original response.
                if name == 'count_tokens' and isinstance(getattr(result, 'total_tokens', None), int):
                    row['counted_input_tokens'] = result.total_tokens
                return result
            finally:
                row['seconds'] = time.perf_counter() - started
                append(row)
        return observed
    try:
        for name in ('generate_content', 'count_tokens'):
            originals[name] = getattr(Models, name)
            setattr(Models, name, wrap(name, originals[name]))
        yield
    finally:
        for name, method in originals.items():
            setattr(Models, name, method)


def report(version, summary_job=None):
    data = dict(version.get('runtime_profile') or {})
    data.update(experiment_id=version['experiment_id'], version_id=version['version_id'], status=version['status'])
    data['availability'] = 'recorded' if version.get('runtime_profile') else 'unavailable_for_historical_version'
    rows = data.get('stages', [])
    data['latency_seconds'] = {name: sum(r['seconds'] for r in rows if r['stage'] == name)
                               if any(r['stage'] == name for r in rows) else None
                               for name in ('preprocess', 'retrieve', 'student')}
    data['latency_scope'] = 'Stage subprocess wall time (includes model load); not GPU kernel-only inference'
    data['automatic_summarization'] = (summary_job or {}).get('runtime_profile')
    return data


def as_csv(data):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(['experiment_id', 'version_id', 'metric', 'value'])
    def flatten(value, key=''):
        if isinstance(value, dict):
            for k, v in value.items():
                flatten(v, key + '.' + k if key else k)
        else:
            writer.writerow([data['experiment_id'], data['version_id'], key,
                             '' if value is None else json.dumps(value, ensure_ascii=False)])
    flatten(data)
    return stream.getvalue()
