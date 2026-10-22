"""Local Flask application. Provider work runs outside request handlers."""
import argparse
import copy
import io
import json
import os
import secrets
import threading
import uuid
import webbrowser
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file, session
from werkzeug.exceptions import HTTPException
from althea_evidence_ui import claims_csv, snapshot_json
from althea_evidence_ui.grounding import NATIVE_ATTRIBUTIONS
from althea_ingestion.common import digest
from .backend import GeminiBackend, LiveBackend, SampleBackend
from .errors import AppError, require
from .preflight import preflight
from .settings import load_settings, project_root, validate_settings

PROVIDERS = {'gemini': GeminiBackend, 'vertex': LiveBackend, 'sample': SampleBackend}


def create_app(*, root=None, settings=None, backend_factories=None):
    root = Path(root or project_root()).resolve()
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secrets.token_hex(32), MAX_CONTENT_LENGTH=21*1024*1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
                      TRUSTED_HOSTS=['localhost', '127.0.0.1', '[::1]'])
    initial = load_settings('live', root=root) if settings is None else validate_settings(settings, root=root)
    state = dict(settings=initial, backends={}, operations={}, active=None)
    mutex = threading.RLock()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='althea-analysis')
    app.extensions['althea'] = state
    app.extensions['althea_executor'] = executor

    def backend(provider):
        require(provider in PROVIDERS, 'Choose Gemini, Google Cloud or the sample.', 'INVALID_INPUT')
        with mutex:
            if provider not in state['backends']:
                configured = validate_settings({**state['settings'], 'provider': 'vertex' if provider in ('vertex','sample') else 'gemini',
                                                'transcribe_model': 'gemini-3.5-transcribe' if provider != 'gemini' else state['settings']['gemini_audio_model']}, root=root)
                factory = (backend_factories or {}).get(provider)
                state['backends'][provider] = factory(configured) if factory else PROVIDERS[provider](configured)
            return state['backends'][provider]

    def public_settings():
        s = state['settings']
        return dict(provider=s['provider'], key_configured=bool(s['api_key']), project_id=s['project_id'] or '',
                    location=s['location'], gemini_audio_model=s['gemini_audio_model'],
                    text_model=s['text_model'], grounding_model=s['grounding_model'])

    def checked_job(provider, job_id):
        require(len(job_id)<=80, 'Unknown analysis.', 'NOT_FOUND')
        b = backend(provider)
        return b, b.load(job_id)

    def submit(provider, callback):
        with mutex:
            require(state['active'] is None, 'An analysis is already running. You can follow it from any page.', 'BUSY')
            operation_id = str(uuid.uuid4())
            state['active'] = operation_id
            state['operations'][operation_id] = dict(id=operation_id, provider=provider, status='running',
                                                     message='Preparing your analysis…', job_id=None)
        def progress(message):
            with mutex: state['operations'][operation_id]['message'] = str(message)
        def run():
            try:
                result = callback(progress)
                with mutex:
                    state['operations'][operation_id].update(status='finished', job_id=result['job_id'],
                        message='Analysis ready' if result['status']=='complete' else 'Analysis saved with an issue to review')
            except Exception as exc:
                with mutex:
                    state['operations'][operation_id].update(status='failed',
                        message=str(exc) if getattr(exc,'code',None) else 'Could not finish this action. Check Settings and try again.')
            finally:
                with mutex:
                    state['active'] = None
                    if len(state['operations'])>100:
                        del state['operations'][next(iter(state['operations']))]
        executor.submit(run)
        return jsonify(operation_id=operation_id), 202

    def mutation_data():
        payload = request.get_json()
        require(isinstance(payload,dict), 'Expected an object.', 'INVALID_INPUT')
        return payload

    @app.before_request
    def protect_local_app():
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin = request.headers.get('Origin')
            require(not origin or origin==request.host_url.rstrip('/'), 'This request came from another website.', 'FORBIDDEN')
            require(bool(session.get('csrf')) and secrets.compare_digest(request.headers.get('X-CSRF-Token',''),session['csrf']),
                    'Refresh this page before trying again.', 'FORBIDDEN')

    @app.after_request
    def response_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers.setdefault('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'")
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(Exception)
    def handle_error(exc):
        if isinstance(exc,HTTPException):
            message = 'This file is too large. Choose audio under 20 MiB (13 MiB with Gemini).' if exc.code==413 else exc.description
            return jsonify(error=message), exc.code
        code = getattr(exc,'code','INTERNAL_ERROR')
        status = 403 if code=='FORBIDDEN' else 404 if code in ('NOT_FOUND','JOB_NOT_FOUND') else 409 if code in ('BUSY','STALE_REVIEW') else 400 if getattr(exc,'code',None) else 500
        return jsonify(error=str(exc) if getattr(exc,'code',None) else 'The action could not finish. Check your local setup and try again.', code=code), status

    @app.get('/')
    @app.get('/history')
    @app.get('/settings')
    @app.get('/jobs/<provider>/<job_id>')
    def shell(provider=None, job_id=None):
        return render_template('index.html')

    @app.get('/api/bootstrap')
    def bootstrap():
        if 'csrf' not in session: session['csrf'] = secrets.token_urlsafe(32)
        with mutex:
            active = copy.deepcopy(state['operations'].get(state['active']))
        return jsonify(csrf=session['csrf'], settings=public_settings(), active=active)

    @app.get('/api/health')
    def health():
        return jsonify(app='althea',interface='web',status='ready')

    @app.get('/api/settings')
    def get_settings():
        report = preflight(state['settings'])
        return jsonify(settings=public_settings(), checks=report['checks'])

    @app.post('/api/settings')
    def save_settings():
        payload = mutation_data()
        allowed = ('provider','project_id','location','gemini_audio_model','text_model','grounding_model')
        with mutex:
            require(state['active'] is None, 'Wait for the current analysis to finish before changing Settings.', 'BUSY')
            updates = {key:payload[key] for key in allowed if key in payload}
            if updates.get('project_id')=='': updates['project_id']=None
            if payload.get('api_key'): updates['api_key']=payload['api_key'].strip()
            if payload.get('clear_key') is True: updates['api_key']=None
            configured = validate_settings({**state['settings'], **updates}, root=root)
            if payload.get('persist') is True:
                env_keys = dict(provider='ALTHEA_PROVIDER', api_key='GEMINI_API_KEY', project_id='GOOGLE_CLOUD_PROJECT',
                    location='GOOGLE_CLOUD_LOCATION', gemini_audio_model='ALTHEA_GEMINI_AUDIO_MODEL',
                    text_model='ALTHEA_TEXT_MODEL', grounding_model='ALTHEA_GROUNDING_MODEL')
                replacements = {env_keys[k]:str(configured[k] or '') for k in updates}
                path = root/'.env'
                lines = path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []
                output=[]
                seen=set()
                for line in lines:
                    name=line.strip().removeprefix('export ').partition('=')[0].strip()
                    if name in replacements:
                        if name not in seen: output.append(f'{name}={replacements[name]}')
                        seen.add(name)
                    else: output.append(line)
                output.extend(f'{name}={value}' for name,value in replacements.items() if name not in seen)
                temporary = path.with_name('.env.'+uuid.uuid4().hex+'.tmp')
                try:
                    temporary.write_text('\n'.join(output)+'\n',encoding='utf-8')
                    os.replace(temporary,path)
                finally:
                    temporary.unlink(missing_ok=True)
            state['settings']=configured
            state['backends'].clear()
        return jsonify(settings=public_settings(), message='Settings saved on this device.' if payload.get('persist') else 'Settings applied for this server session.')

    @app.get('/api/jobs')
    def history():
        jobs=[]
        for provider in PROVIDERS:
            for job in backend(provider).list_jobs(100): jobs.append({**job,'provider':provider})
        return jsonify(jobs=sorted(jobs,key=lambda job:job['updated_at'],reverse=True))

    @app.post('/api/jobs')
    def analyze():
        with mutex: require(state['active'] is None, 'An analysis is already running.', 'BUSY')
        kind = request.form.get('kind','audio')
        provider = 'sample' if kind=='sample' else request.form.get('provider',state['settings']['provider'])
        b = backend(provider)
        title = request.form.get('title','').strip() or ('Riverton sample' if kind=='sample' else 'Untitled conversation')
        require(len(title)<=160, 'Keep the title under 160 characters.', 'INVALID_INPUT')
        if kind=='sample':
            source=dict(kind='sample',local_path=None,sample_id='riverton_demo',title=title)
        else:
            require(provider!='sample', 'Select an audio provider.', 'INVALID_INPUT')
            require(provider!='gemini' or bool(b.settings['api_key']), 'Add your Gemini API key in Settings first.', 'PROVIDER_AUTH')
            upload = request.files.get('file')
            require(upload is not None and bool(upload.filename), 'Choose a recording first.', 'INVALID_INPUT')
            suffix = Path(upload.filename).suffix.lower()
            require(suffix in ('.mp3','.wav','.json'), 'Choose MP3, WAV or a complete transcript JSON file.', 'INVALID_INPUT')
            cap = 13*1024*1024 if provider=='gemini' and suffix!='.json' else 20*1024*1024
            raw=upload.stream.read(cap+1)
            require(0<len(raw)<=cap, f'Choose a nonempty file under {cap//1024//1024} MiB.', 'INVALID_INPUT')
            folder=(Path(b.settings['data_dir'])/'uploads').resolve()
            require(folder.is_relative_to(Path(b.settings['data_dir']).resolve()), 'Invalid upload storage.', 'INVALID_INPUT')
            folder.mkdir(parents=True,exist_ok=True)
            path=folder/(str(uuid.uuid4())+suffix)
            path.write_bytes(raw)
            path.with_suffix('.upload.json').write_text(json.dumps({'original_filename':upload.filename[:512]}),encoding='utf-8')
            source=dict(kind='transcript' if suffix=='.json' else 'audio',local_path=str(path),sample_id=None,title=title)
        verify=request.form.get('verify')=='true'
        return submit(provider,lambda progress:b.run(source,verify=verify,progress=progress))

    @app.get('/api/operations/<operation_id>')
    def operation(operation_id):
        with mutex:
            require(operation_id in state['operations'], 'This operation is no longer active. Your saved results are in History.', 'NOT_FOUND')
            return jsonify(copy.deepcopy(state['operations'][operation_id]))

    @app.get('/api/jobs/<provider>/<job_id>')
    def job(provider,job_id):
        b,s = checked_job(provider,job_id)
        versions=[{k:v for k,v in version.items() if k!='payload'} for version in b.artifact_history(job_id)]
        return jsonify(snapshot=s,usage=b.job_usage(job_id),versions=versions)

    @app.post('/api/jobs/<provider>/<job_id>/review')
    def review(provider,job_id):
        payload=mutation_data()
        with mutex:
            require(state['active'] is None, 'Wait for the current analysis before editing a transcript.', 'BUSY')
            b,s=checked_job(provider,job_id)
            require(s['transcript'] is not None, 'There is no transcript to edit.', 'INVALID_INPUT')
            require(payload.get('transcript_id')==s['transcript']['transcript_id'], 'This transcript changed. Reload it before saving your review.', 'STALE_REVIEW')
            return jsonify(snapshot=b.save_review(job_id,payload.get('transcript')))

    @app.post('/api/jobs/<provider>/<job_id>/actions')
    def job_action(provider,job_id):
        payload=mutation_data()
        b,s=checked_job(provider,job_id)
        action=payload.get('action')
        require(action in ('reanalyze','verify','refresh'), 'Choose a valid analysis action.', 'INVALID_INPUT')
        if action=='reanalyze': return submit(provider,lambda progress:b.reanalyze(job_id,verify=payload.get('verify') is True,progress=progress))
        pairs=payload.get('pair_ids')
        require(isinstance(pairs,list) and 0<len(pairs)<=4, 'Select one to four disagreements.', 'INVALID_INPUT')
        from .validation import requested_pairs
        require(s['analysis'] is not None, 'Analyze the transcript first.', 'INVALID_INPUT')
        requested_pairs(s['analysis'],pairs,4)
        return submit(provider,lambda progress:b.verify_pairs(job_id,pairs,progress=progress) if action=='verify' else b.refresh_verification(job_id,pairs,progress=progress))

    @app.get('/api/jobs/<provider>/<job_id>/export/<format>')
    def export(provider,job_id,format):
        b,s=checked_job(provider,job_id)
        require(format in ('json','csv'), 'Unknown export format.', 'NOT_FOUND')
        data=snapshot_json(s) if format=='json' else claims_csv(s)
        return send_file(io.BytesIO(data),mimetype='application/json' if format=='json' else 'text/csv',as_attachment=True,download_name='althea-'+job_id+'.'+format)

    @app.get('/api/jobs/<provider>/<job_id>/versions/<artifact_id>')
    def version_export(provider,job_id,artifact_id):
        b,_=checked_job(provider,job_id)
        version=next((v for v in b.artifact_history(job_id) if v['artifact_id']==artifact_id),None)
        require(version is not None, 'Unknown saved version.', 'NOT_FOUND')
        return send_file(io.BytesIO(json.dumps(version['payload'],ensure_ascii=False,indent=2).encode()),mimetype='application/json',as_attachment=True,download_name='althea-saved-version.json')

    @app.get('/api/jobs/<provider>/<job_id>/audio')
    def audio(provider,job_id):
        b,s=checked_job(provider,job_id)
        relative=(s['transcript'] or {}).get('source',{}).get('audio_relpath')
        require(isinstance(relative,str) and relative.startswith('media/'), 'Audio is unavailable for this transcript.', 'NOT_FOUND')
        media_root=(Path(b.settings['data_dir'])/'media').resolve()
        path=(Path(b.settings['data_dir'])/relative).resolve()
        require(path.is_relative_to(media_root) and path.suffix in ('.mp3','.wav') and path.is_file(), 'Audio is unavailable.', 'NOT_FOUND')
        return send_file(path,mimetype='audio/mpeg' if path.suffix=='.mp3' else 'audio/wav',conditional=True)

    @app.get('/api/jobs/<provider>/<job_id>/attributions/<pair_id>')
    def attribution(provider,job_id,pair_id):
        _,s=checked_job(provider,job_id)
        item=next((a for a in (s['verification'] or {}).get('grounding_attributions',[]) if a['pair_id']==pair_id),None)
        require(item is not None and digest(item) in NATIVE_ATTRIBUTIONS, 'Native Search attribution is unavailable for this result.', 'NOT_FOUND')
        response=Response(item['search_entry_point_html'],mimetype='text/html')
        response.headers['Content-Security-Policy']="default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; font-src https: data:; frame-ancestors 'self'; base-uri 'none'"
        return response

    return app


def main():
    parser=argparse.ArgumentParser(description='Althea AI local web application')
    parser.add_argument('--port',type=int,default=5000)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    from waitress import create_server
    url=f'http://127.0.0.1:{args.port}'
    try:
        with urlopen(url+'/api/health',timeout=1) as response:
            existing=json.load(response)
        if existing.get('app')=='althea' and existing.get('interface')=='web':
            print(f'Althea AI is already running: {url}',flush=True)
            if not args.no_browser:webbrowser.open(url)
            return
    except (OSError,ValueError):
        pass
    app=create_app()
    server=create_server(app,host='127.0.0.1',port=args.port,threads=6,max_request_body_size=21*1024*1024)
    print(f'Althea AI: {url}\nKeep this console open. Press Ctrl+C to stop.',flush=True)
    if not args.no_browser:
        timer=threading.Timer(1.5,lambda:webbrowser.open(url))
        timer.daemon=True
        timer.start()
    try:server.run()
    except KeyboardInterrupt:pass
    finally:server.close()


if __name__=='__main__':main()
