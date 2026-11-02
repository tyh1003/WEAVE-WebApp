"""Token-scoped research API; never serve the legacy global output directory."""
import os
import subprocess
import sys
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file
from research_store import Store, ResearchError

bp = Blueprint('research', __name__)
BASE = Path(__file__).resolve().parent


@bp.get('/experiments/<eid>/versions/<vid>/runtime-profile')
def runtime_profile(eid, vid):
    from runtime_profile import report, as_csv
    from automatic_summaries import state
    storage, _ = authorize(eid)
    version = storage.version(eid, vid)
    # Numeric telemetry only: never return prompts, labels, paths or diagnostics.
    data = report(version, state(storage.root, eid, vid))
    if request.args.get('format') == 'csv':
        return current_app.response_class(as_csv(data), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename="runtime-profile.csv"'})
    return jsonify(data)


def store():
    return Store(current_app.config.get('RESEARCH_ROOT', os.getenv('WEAVE_RESEARCH_ROOT', str(BASE / 'research_data'))))


def authorize(eid):
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer ') or not header[7:]:
        raise ResearchError('Experiment access token required', 401)
    storage = store()
    return storage, storage.experiment(eid, header[7:])


def body_object():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ResearchError('Expected a JSON object', 400)
    return body


def launch(storage):
    if current_app.config.get('RESEARCH_DISPATCH'):
        current_app.config['RESEARCH_DISPATCH'](storage)
        return
    # Worker is independent from Flask restart and holds the cross-process lock.
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    subprocess.Popen([sys.executable, str(BASE / 'research_runner.py'), str(storage.root)],
                     cwd=BASE, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags,
                     start_new_session=os.name != 'nt')


@bp.errorhandler(ResearchError)
def research_error(error):
    return jsonify(error=str(error)), error.status


@bp.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.post('/experiments')
def create():
    file = request.files.get('video')
    if not file or not file.filename:
        raise ResearchError('video is required', 400)
    # Resolve dataset identity privately, before assigning a neutral asset filename.
    label, dataset_id = current_app.config['RESEARCH_GT_LOOKUP'](file.filename)
    storage = store()
    exp, token = storage.create(file, label, dataset_id)
    return jsonify(experiment=storage.public_experiment(exp), access_token=token), 201


@bp.get('/experiments/<eid>')
def experiment(eid):
    storage, exp = authorize(eid)
    return jsonify(storage.public_experiment(exp))


@bp.get('/experiments/<eid>/video')
def video(eid):
    _, exp = authorize(eid)
    return send_file(exp['video_path'], download_name=exp['safe_display_filename'], conditional=True)


@bp.post('/experiments/<eid>/human-judgment')
def judgment(eid):
    storage, _ = authorize(eid)
    body = body_object()
    exp = storage.lock_human(eid, body.get('vote'), body.get('reason', ''))
    return jsonify(storage.public_experiment(exp))


@bp.route('/experiments/<eid>/versions', methods=['GET', 'POST'])
def versions(eid):
    storage, _ = authorize(eid)
    if request.method == 'POST':
        version, created = storage.create_version(eid, body_object())
        if version['status'] == 'pending':
            try:
                launch(storage)
            except OSError:
                storage.update(eid, version['version_id'], status='failed', stage='error', error='Worker could not be started')
                version = storage.version(eid, version['version_id'])
        return jsonify(storage.public_version(version, storage.reveal(eid))), 201 if created else 200
    # Recover an interrupted worker on polling, never create new work from a GET.
    records = storage.versions(eid)
    if any(v['status'] in ('pending', 'running') for v in records):
        launch(storage)
    return jsonify(versions=[storage.public_version(v, storage.reveal(eid)) for v in records])


@bp.get('/experiments/<eid>/versions/<vid>/status')
@bp.get('/experiments/<eid>/versions/<vid>/result')
def version_result(eid, vid):
    storage, _ = authorize(eid)
    version = storage.version(eid, vid)
    return jsonify(storage.public_version(version, storage.reveal(eid)))


@bp.get('/experiments/<eid>/versions/<vid>/automatic-summaries')
def automatic_summaries(eid, vid):
    from automatic_summaries import state
    storage, _ = authorize(eid)
    storage.version(eid, vid)
    if not storage.reveal(eid):
        raise ResearchError('Baseline disclosure required', 409)
    # Read-only status retrieval never dispatches or retries paid work.
    return jsonify(state(storage.root, eid, vid))


@bp.route('/experiments/<eid>/versions/<vid>/evidence-assessment', methods=['GET', 'POST'])
def version_evidence_assessment(eid, vid):
    from version_assessment import CONFIG, describe
    storage, _ = authorize(eid)
    version = storage.version(eid, vid)
    if not storage.reveal(eid) or version['status'] != 'succeeded':
        raise ResearchError('A disclosed successful version is required', 409)
    if request.method == 'POST' and body_object().get('confirm_cost') is not True:
        raise ResearchError('Explicit model-cost confirmation required', 400)
    from evidence_assessment import live_settings
    if 'EVIDENCE_ASSESSMENT_CONFIG' in current_app.config or 'EVIDENCE_ASSESSMENT_PROVIDER' in current_app.config:
        config=current_app.config.get('EVIDENCE_ASSESSMENT_CONFIG', CONFIG)
        provider=current_app.config.get('EVIDENCE_ASSESSMENT_PROVIDER')
    else:
        config, provider = live_settings()
    return jsonify(describe(version, storage.root, config=config, provider=provider,
        execute=request.method == 'POST'))


@bp.route('/experiments/<eid>/versions/<vid>/grounded-explanation', methods=['GET', 'POST'])
def grounded_explanation(eid, vid):
    from grounded_explanation import describe
    from version_assessment import CONFIG
    from evidence_assessment import live_settings
    storage, _ = authorize(eid)
    version = storage.version(eid, vid)
    if not storage.reveal(eid) or version['status'] != 'succeeded':
        raise ResearchError('A disclosed successful version is required', 409)
    if request.method == 'POST' and body_object().get('confirm_cost') is not True:
        raise ResearchError('Explicit model-cost confirmation required', 400)
    if 'EVIDENCE_ASSESSMENT_PROVIDER' in current_app.config:
        config = current_app.config.get('EVIDENCE_ASSESSMENT_CONFIG', CONFIG)
        provider = current_app.config['EVIDENCE_ASSESSMENT_PROVIDER']
    else:
        config, provider = live_settings()
    return jsonify(describe(version, storage.root, config, provider, request.method == 'POST',
        retry_of=body_object().get('retry_of') if request.method == 'POST' else None))


@bp.get('/experiments/<eid>/versions/<vid>/source-grounded-preview')
def source_grounded_preview(eid, vid):
    from source_grounded import plan
    storage, _ = authorize(eid)
    version=storage.version(eid,vid)
    if not storage.reveal(eid) or version['status']!='succeeded':
        raise ResearchError('A disclosed successful parent version is required',409)
    try:
        manifest=plan(version)
    except ValueError as error:
        return jsonify(available=False,error=str(error),manifest=None)
    return jsonify(available=bool(manifest['units']),manifest=manifest,
                   error=None if manifest['units'] else 'No eligible saved article body')


@bp.post('/experiments/<eid>/versions/<vid>/source-ablation-preview')
def source_ablation_preview(eid, vid):
    from source_ablation import plan
    storage, _ = authorize(eid)
    if not storage.reveal(eid):
        raise ResearchError('A disclosed successful parent is required',409)
    try:
        result=plan(storage.version(eid,vid),body_object().get('excluded_unit_ids',[]))
    except (ValueError, KeyError, TypeError) as error:
        raise ResearchError(str(error),400) from error
    return jsonify(result)


@bp.get('/experiments/<eid>/versions/<vid>/source-aware-preview')
def source_aware_preview(eid, vid):
    from source_summarization import state
    storage, _ = authorize(eid)
    version=storage.version(eid,vid)
    if not storage.reveal(eid) or version['status']!='succeeded':
        raise ResearchError('A disclosed successful parent version is required',409)
    return jsonify(state(version,storage.root))


@bp.post('/experiments/<eid>/versions/<vid>/source-summaries')
def source_summaries(eid,vid):
    from source_summarization import generate
    storage, _ = authorize(eid)
    version=storage.version(eid,vid)
    if not storage.reveal(eid) or version['status']!='succeeded':
        raise ResearchError('A disclosed successful parent version is required',409)
    try:
        return jsonify(generate(version,storage.root,body_object(),current_app.config.get('SOURCE_SUMMARIZATION_PROVIDER')))
    except ValueError as error:
        raise ResearchError(str(error),400) from error


@bp.post('/experiments/<eid>/versions/<vid>/source-summary-review')
def source_summary_review(eid,vid):
    from source_summarization import review
    storage, _ = authorize(eid)
    version=storage.version(eid,vid)
    if not storage.reveal(eid) or version['status']!='succeeded':
        raise ResearchError('A disclosed successful parent version is required',409)
    try:
        return jsonify(review(version,storage.root,body_object()))
    except ValueError as error:
        raise ResearchError(str(error),409) from error
