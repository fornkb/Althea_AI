"""Presentation depends only on backend factories, never other team packages."""
import copy
import uuid
from pathlib import Path
from .exports import claims_csv, snapshot_json, safe_text
from .common import normalize_url, digest
from .errors import require
from .presentation import apply_style,header,transcript_turn,scope_details


def mmss(value):
    seconds = int(value)
    return f'{seconds//60:02d}:{seconds%60:02d}'


def playback_path(data_dir, relative):
    if not relative or not data_dir:
        return None
    root = Path(data_dir).resolve()
    path = (root/relative).resolve()
    return path if not Path(relative).is_absolute() and path.is_relative_to(root) and path.is_file() else None


def save_upload(upload, data_dir):
    raw = upload.getvalue()
    require(0 < len(raw) <=20*1024*1024,'Upload must be nonempty and <=20 MiB.')
    suffix = Path(upload.name).suffix.lower()
    require(suffix in ('.mp3','.wav','.json'),'Unsupported upload format.')
    root = Path(data_dir).resolve()
    folder = (root/'uploads').resolve()
    require(folder.is_relative_to(root),'Upload directory escapes data_dir.')
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/(str(uuid.uuid4())+suffix)
    with path.open('xb') as f:
        f.write(raw)
    # Keep the display name separately; it never becomes a filesystem target.
    import json
    path.with_suffix('.upload.json').write_text(json.dumps({'original_filename':upload.name},ensure_ascii=False),encoding='utf-8')
    return dict(kind='transcript' if suffix=='.json' else 'audio',local_path=str(path),sample_id=None)


def connection_settings(st, backend, label):
    """Only the Settings view renders credentials. Backends retain session keys."""
    settings=getattr(backend,'settings',{})
    if getattr(backend,'requires_api_key',False):
        widget_key='gemini_api_key_'+label
        with st.form('api_key_'+label):
            supplied_key=st.text_input('Gemini API key',type='password',key=widget_key,help='Held in this app session. It is not saved in jobs, cache keys or exports.')
            apply_key=st.form_submit_button('Use API key',type='primary')
        if apply_key:
            try:
                require(bool(supplied_key.strip()),'Enter a Gemini API key.')
                backend.configure_api_key(supplied_key.strip())
                settings=backend.settings
            except Exception as exc:
                st.error(str(exc))
        def clear_key():
            backend.configure_api_key(None)
            st.session_state[widget_key]=''
        st.button('Clear API key',on_click=clear_key)
        if settings.get('api_key'):st.success('API key configured for this session.')
        else:st.info('Add a key to enable audio analysis. The fictional sample works without one.')
        st.link_button('Get a Gemini API key','https://aistudio.google.com/')
        st.caption('Keys entered here last for this session. To keep a key across restarts, set GEMINI_API_KEY in the root .env file and restart the app. Entering a key makes no API request. Audio/text quotas apply; Google Search evidence checks with Gemini 3.5 Flash-Lite require the paid tier.')
    elif backend.mode=='live':
        st.caption('Google Cloud uses the project and credentials configured on this computer.')
        st.text('Project: '+(settings.get('project_id') or 'Not configured'))
    else:
        st.info('This standalone workspace supports the fictional sample only.')
    if backend.mode=='live':
        import shutil
        if not all(shutil.which(tool) for tool in ('ffmpeg','ffprobe')):
            st.warning('Audio processing needs FFmpeg and ffprobe on this computer. Install both before analyzing recordings or uploads. Transcript JSON import still works.')
        st.caption('Audio: English · Up to 5 minutes · '+('13 MiB' if getattr(backend,'requires_api_key',False) else '20 MiB'))
        st.caption('Audio and transcript text are sent to your selected provider only when you request analysis or evidence checks.')


def render_app(backends: dict) -> None:
    import streamlit as st
    st.set_page_config(page_title='Althea AI',page_icon='🎙️',layout='wide')
    apply_style(st)
    def navigate(page):st.session_state['althea_page']=page
    page=st.session_state.get('althea_page','Home')
    with st.container(key='top_navigation'):
        brand,home,history_nav,settings_nav=st.columns([5,1.2,1.2,1.4])
        brand.markdown('<div class="brand"><div class="brand-mark">a</div><div class="brand-name">althea<small>AI</small></div></div>',unsafe_allow_html=True)
        for column,name,icon in [(home,'Home',':material/home:'),(history_nav,'History',':material/history:'),(settings_nav,'Settings',':material/settings:')]:
            column.button(name,icon=icon,type='primary' if page==name else 'tertiary',use_container_width=True,on_click=navigate,args=(name,))
    live_labels=[name for name in backends if name!='Sample demo']
    sample_label='Sample demo' if 'Sample demo' in backends else next(iter(backends))
    if 'althea_provider' not in st.session_state:
        st.session_state['althea_provider']='Gemini API key' if 'Gemini API key' in backends else next(iter(backends))
    def get_backend(label):
        key='althea_backend_'+label
        if key not in st.session_state:st.session_state[key]=backends[label]()
        return st.session_state[key]
    if page=='History':
        st.title('Your conversations')
        st.caption('Return to a saved analysis. Loading a conversation makes no new provider request.')
        entries=[]
        for name in backends:
            entries.extend((name,job) for job in get_backend(name).list_jobs())
        if not entries:st.info('No saved analyses yet. Start with an upload, a recording, or the fictional sample on Home.')
        else:
            selected=st.selectbox('Saved conversations',range(len(entries)),format_func=lambda i:entries[i][1]['title']+' · '+entries[i][0])
            provider,job=entries[selected]
            st.caption('Status: '+job['status'].capitalize())
            if st.button('Open analysis',type='primary'):
                st.session_state['althea_snapshot_'+provider]=get_backend(provider).load(job['job_id'])
                st.session_state['althea_input_choice']='Try sample' if provider==sample_label else 'Upload audio'
                if provider!=sample_label:st.session_state['althea_provider']=provider
                navigate('Home');st.rerun()
        return
    if page=='Settings':
        st.title('Settings')
        st.caption('Manage your analysis connection. Credentials stay out of your workspace.')
        options=live_labels or [sample_label]
        current=st.session_state['althea_provider']
        label=st.selectbox('Analysis provider',options,index=options.index(current) if current in options else 0)
        st.session_state['althea_provider']=label
        connection_settings(st,get_backend(label),label)
        return
    methods=['Upload audio','Record debate','Try sample'] if live_labels else ['Try sample']
    method=st.session_state.get('althea_input_choice',methods[0])
    if method not in methods:method=methods[0]
    label=sample_label if method=='Try sample' else st.session_state['althea_provider']
    backend=get_backend(label)
    settings=getattr(backend,'settings',{})
    state_key = 'althea_snapshot_'+label
    header(st,has_result=bool(st.session_state.get(state_key)))
    persistence='saved jobs stored locally' if getattr(backend,'persistent',False) else 'session-only saved jobs'
    if backend.mode=='fixture':st.info('Fictional sample · No external requests · '+persistence)
    history = backend.list_jobs()
    if history:
        ids = ['']+[j['job_id'] for j in history]
        titles = {j['job_id']:j['title'] for j in history}
        with st.expander('Recent analyses',expanded=False):
            chosen = st.selectbox('Saved jobs',ids,format_func=lambda x:titles.get(x,'Choose a job'),key='history_'+label)
            if chosen and st.button('Load saved job'):
                st.session_state[state_key] = backend.load(chosen)
                st.rerun()
    def choose_input():
        st.session_state['althea_input_choice']=st.session_state['althea_input_widget']
    def open_settings():st.session_state['althea_page']='Settings'
    def set_method(value):
        st.session_state['althea_input_choice']=value
        st.session_state['althea_input_widget']=value
    has_result=bool(st.session_state.get(state_key))
    workspace,guide=st.columns([1.95,1],gap='large') if not has_result else (st.container(),None)
    if guide is not None:
        with guide:
            st.markdown('<div class="guide-panel"><h3>From audio to understanding.</h3><p>A thoughtful second look at what was said.</p><div class="guide-step"><span>1</span><div><h4>Bring the conversation</h4><p>Upload a debate or record directly from your microphone.</p></div></div><div class="guide-step"><span>2</span><div><h4>Review what matters</h4><p>Read the transcript, correct speakers, and compare claims in context.</p></div></div><div class="guide-step"><span>3</span><div><h4>Follow the evidence</h4><p>Choose potential disagreements to check against retrieved sources.</p></div></div><div class="guide-note">Evidence can support, refute, or leave a claim unresolved. Althea does not pick a winner.</div></div>',unsafe_allow_html=True)
            if live_labels:st.button('Explore the sample',icon=':material/play_circle:',use_container_width=True,on_click=set_method,args=('Try sample',))
    area=workspace.expander('New analysis',expanded=False) if has_result else workspace.container(key='audio_workspace')
    with area:
        st.markdown('<div class="workspace-heading"><div class="mic-symbol"><svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0014 0v-2M12 19v3M8 22h8"/></svg></div><div><h3>Start a conversation analysis</h3><p>Your next insight starts with the audio.</p></div></div>',unsafe_allow_html=True)
        if 'althea_input_widget' not in st.session_state:st.session_state['althea_input_widget']=method
        st.radio('Input method',methods,index=None,horizontal=True,key='althea_input_widget',on_change=choose_input,label_visibility='collapsed')
        with st.container():
            left,right=st.columns([2,1]) if backend.mode=='fixture' else (st.container(),None)
            title = left.text_input('Job title',value='Riverton sample — fictional' if backend.mode=='fixture' else 'Debate analysis')
            sample = right.selectbox('Sample',['riverton_demo'],format_func=lambda _: 'Riverton debate') if backend.mode=='fixture' else None
            if method=='Record debate':
                st.caption('Press the microphone to start. Stop within 5 minutes, then listen back before analyzing.')
                upload=st.audio_input('Record debate audio',sample_rate=16000,key='recording_'+label,width=320,help='Your browser will ask for microphone permission. Recording does not start an analysis.')
            elif method=='Upload audio':
                upload=st.file_uploader('Upload debate audio',type=['mp3','wav'],key='audio_upload_'+label)
                st.button('Use microphone instead',icon=':material/mic:',key='recorder_shortcut',on_click=set_method,args=('Record debate',))
                with st.expander('Import an existing transcript instead'):
                    imported=st.file_uploader('Transcript JSON',type=['json'],key='transcript_upload_'+label)
                if upload is None:upload=imported
            else:upload=None
            if backend.mode=='fixture':
                st.caption('A fictional two-speaker debate · 8 turns · No recording or API key needed.')
            else:
                st.caption('English · MP3 / WAV · Up to 5 minutes · '+('13 MiB audio' if getattr(backend,'requires_api_key',False) else '20 MiB audio'))
            if getattr(backend,'requires_api_key',False):
                st.caption('Speaker turns and timings are model-generated. Review playback before relying on claims.')
            check = st.checkbox('Check up to four disagreements against web evidence',value=False)
            missing_key=bool(getattr(backend,'requires_api_key',False) and not settings.get('api_key'))
            if missing_key:
                st.caption('One quick setup: connect your provider in Settings, or explore the sample without a key.')
                st.button('Open Settings',icon=':material/arrow_forward:',on_click=open_settings)
            size_limit=13*1024*1024 if getattr(backend,'requires_api_key',False) else 20*1024*1024
            oversized=upload is not None and len(upload.getvalue())>size_limit
            if oversized:st.error('This file exceeds the audio size limit. Compress it or choose a smaller file.')
            analyze = st.button('Analyze',type='primary',use_container_width=True,disabled=bool(st.session_state.get('althea_running')) or missing_key or oversized or (backend.mode!='fixture' and upload is None))
    if analyze and not st.session_state.get('althea_running'):
        st.session_state['althea_running'] = True
        refresh_page=False
        try:
            require(bool(title.strip()),'Enter a job title.')
            require(backend.mode=='fixture' or upload is not None,'Record or upload debate audio before choosing Analyze.')
            source = dict(kind='sample',sample_id=sample,local_path=None)
            if upload:
                require(backend.mode!='fixture','Choose the sample; arbitrary uploads require the integrated live backend.')
                source = save_upload(upload,settings['data_dir'])
            with st.status('Analyzing input…',expanded=True) as status:
                result = backend.run({**source,'title':title},verify=check,progress=st.write)
                st.session_state[state_key] = result
                status.update(label='Analysis finished' if result['status']=='complete' else 'Some stages could not finish; saved work is available below',state='complete' if result['status']=='complete' else 'error')
                refresh_page=True
        except Exception as exc:
            st.error(str(exc))
        finally:
            st.session_state['althea_running'] = False
        if refresh_page:
            st.rerun()
    s = st.session_state.get(state_key)
    if not s:
        st.info('Choose Analyze to explore the fictional sample, or load a saved job.' if backend.mode=='fixture' else 'Record or upload debate audio to start an analysis, or load a saved job.')
        st.markdown('<div class="site-footer"><span>Althea AI · Clarity, claim by claim.</span><span>Saved on this device. Reviewed by you.</span></div>',unsafe_allow_html=True)
        return
    if getattr(backend,'persistent',False):
        s=backend.load(s['job_id'])  # pure read: other sessions' reviews cannot leave stale cards
        st.session_state[state_key]=s
    st.subheader(s['title'])
    from datetime import datetime
    updated=datetime.fromisoformat(s['updated_at'].replace('Z','+00:00')).strftime('%d %b %Y · %H:%M UTC')
    st.caption(f"{s['status'].replace('_',' ').capitalize()} · Updated {updated}")
    t, a, v = s['transcript'],s['analysis'],s['verification']
    stats=st.columns(4)
    stats[0].metric('Speaker turns',len((t or {}).get('segments',[])))
    stats[1].metric('Claims',len((a or {}).get('claims',[])))
    stats[2].metric('Potential disagreements',sum(p['relation'] in ('direct_conflict','numeric_discrepancy') for p in (a or {}).get('pairs',[])))
    stats[3].metric('Evidence checks',len((v or {}).get('results',[])))
    if hasattr(backend,'job_usage'):
        usage=backend.job_usage(s['job_id'])
        with st.expander('Usage & limits'):
            st.caption(f"Provider attempts: {usage['attempts_used']}/{usage['attempt_limit']} · Distinct evidence pairs: {usage['verification_pairs_used']}/{usage['pair_limit']} · New attempts in last action: {usage['new_attempts_this_action']} · New attempts since opening this mode: {usage['attempts_this_session']}")
            if usage['cache_hits']:
                st.caption('Reused historical results without new provider calls: '+', '.join(usage['cache_hits']))
        if usage['attempts_used']>=usage['attempt_limit']:
            st.warning('The provider-attempt budget is exhausted. Saved and cached results remain available; new evidence refreshes need unused attempts.')
        if usage['verification_pairs_used']>=usage['pair_limit']:
            st.info('The distinct-pair limit is reached. Previously reserved pairs may be revisited; new pairs cannot be added to this job.')
    for issue in s['issues']:
        st.warning(issue['message'])
    transcript_tab, claims_tab, conflicts_tab, evidence_tab = st.tabs(['Transcript','Claims','Disagreements','Evidence & Export'])
    speakers = {sp['speaker_id']:sp['display_name'] for sp in t['speakers']} if t else {}
    segments = {seg['segment_id']:seg for seg in t['segments']} if t else {}
    claims = {c['claim_id']:c for c in a['claims']} if a else {}
    def action(callback):
        try:
            with st.spinner('Working…'):
                st.session_state[state_key] = callback()
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    with transcript_tab:
        if not t:
            st.info('No transcript available.')
        else:
            st.caption('Transcript origin: '+t['origin'])
            for transcription_issue in t['issues']:
                st.warning(transcription_issue['message'])
            audio = playback_path(settings.get('data_dir'),t['source']['audio_relpath'])
            if audio:
                st.audio(str(audio))
            else:
                st.info('Transcript sample; audio unavailable' if s['mode']=='fixture' else 'Audio unavailable')
            for segment in t['segments']:
                index = next(i for i,sp in enumerate(t['speakers']) if sp['speaker_id']==segment['speaker_id'])
                transcript_turn(st,time=mmss(segment['start_s'])+'–'+mmss(segment['end_s']),speaker=speakers[segment['speaker_id']],text=segment['text'],alternate=bool(index%2))
            with st.expander('Review transcript and speaker names'):
                st.warning('Saved edits are human-reviewed. Saving clears claims and evidence; choose Reanalyze afterward.')
                prefix = s['job_id']+t['transcript_id']
                with st.form('review_'+prefix):
                    edited = copy.deepcopy(t)
                    for sp in edited['speakers']:
                        sp['display_name'] = st.text_input('Name · '+sp['speaker_id'],sp['display_name'],key=prefix+sp['speaker_id'])
                    for seg in edited['segments']:
                        sid = seg['segment_id']
                        st.caption(sid)
                        seg['text'] = st.text_area('Text · '+sid,seg['text'],key=prefix+sid+'text')
                        left,middle,right = st.columns(3)
                        seg['speaker_id'] = left.selectbox('Speaker · '+sid,list(speakers),index=list(speakers).index(seg['speaker_id']),format_func=lambda x:speakers[x],key=prefix+sid+'speaker')
                        seg['start_s'] = middle.number_input('Start · '+sid,min_value=0.0,value=float(seg['start_s']),step=.001,format='%.3f',key=prefix+sid+'start')
                        seg['end_s'] = right.number_input('End · '+sid,min_value=0.0,value=float(seg['end_s']),step=.001,format='%.3f',key=prefix+sid+'end')
                    saved = st.form_submit_button('Save review',type='primary')
                if saved:
                    action(lambda:backend.save_review(s['job_id'],edited))
            if a is None and st.button('Reanalyze'):
                action(lambda:backend.reanalyze(s['job_id'],verify=check,progress=None))
    with claims_tab:
        if not claims:
            st.info('No factual claims available. Analyze the transcript to populate the ledger.')
        else:
            left,middle,right = st.columns(3)
            speaker_filter = left.selectbox('Speaker filter',['All']+list(speakers),format_func=lambda x:speakers.get(x,x))
            topic = middle.selectbox('Subject filter',['All']+sorted({c['subject'] for c in claims.values() if c['subject']}))
            checkability = right.selectbox('Checkability filter',['All','checkable','needs_context'])
            rows = []
            for c in claims.values():
                if speaker_filter!='All' and c['speaker_id']!=speaker_filter or topic!='All' and c['subject']!=topic or checkability!='All' and c['checkability']!=checkability:
                    continue
                q = c['quantity'] or {}
                rows.append(dict(Claim=c['claim_id'],Speaker=speakers[c['speaker_id']],Proposition=c['proposition'],Quote='\n'.join(x['quote'] for x in c['source_spans']),Time=mmss(segments[c['source_spans'][0]['segment_id']]['start_s']),Period=c['period'],Geography=c['geography'],Basis=c['measurement_basis'],Value=q.get('value'),Unit=q.get('unit'),Missing_context='; '.join(c['missing_context'])))
            # The grid has its own CSV download. For formula-bearing raw text,
            # use a table without that bypass; only the escaped export is offered.
            if any(isinstance(value,str) and safe_text(value)!=value for row in rows for value in row.values()):
                st.table(rows)
            else:
                st.dataframe(rows,hide_index=True,width='stretch',column_order=['Speaker','Proposition','Value','Unit','Period','Time'])
            detail = st.selectbox('Exact quotation and scope',list(claims),format_func=lambda cid:claims[cid]['proposition'])
            selected_claim = claims[detail]
            for span in selected_claim['source_spans']:
                segment = segments[span['segment_id']]
                st.caption(speakers[selected_claim['speaker_id']]+' · '+mmss(segment['start_s'])+'–'+mmss(segment['end_s']))
                st.text(span['quote'])
            scope_details(st,selected_claim)
            if selected_claim['missing_context']:
                st.warning('Missing context: '+', '.join(selected_claim['missing_context']))
    with conflicts_tab:
        pairs = [p for p in (a or {}).get('pairs',[]) if p['relation'] in ('direct_conflict','numeric_discrepancy')]
        limit = min(settings.get('max_display_conflicts',8),8)
        st.caption(f'{len(pairs)} potential disagreements · four distinct verification pairs per job, including previous analyses')
        if not pairs:
            st.info('No potential disagreements found.')
        if len(pairs)>limit:
            st.warning('Showing the highest-priority eight disagreements. All pairs remain in JSON export.')
        selected = []
        states = {r['pair_id']:'checked' for r in (v or {}).get('results',[])}
        states.update({r['pair_id']:r['reason'] for r in (v or {}).get('unverified',[])})
        for p in sorted(pairs,key=lambda p:(p['priority'],p['pair_id']))[:limit]:
            with st.container(border=True):
                st.subheader(p['relation'].replace('_',' ').capitalize())
                st.caption(p['pair_id'])
                for column,cid in zip(st.columns(2),(p['claim_a_id'],p['claim_b_id'])):
                    c = claims[cid]
                    column.caption(speakers[c['speaker_id']]+' · '+mmss(segments[c['source_spans'][0]['segment_id']]['start_s']))
                    column.text('\n'.join(span['quote'] for span in c['source_spans']))
                st.text(p['explanation'])
                if p['numeric_difference'] is not None:
                    st.caption('Absolute difference: '+p['numeric_difference']+' '+p['numeric_difference_unit'])
                st.caption('Evidence state: '+states.get(p['pair_id'],'not checked'))
                if st.checkbox('Select '+p['pair_id'],key=s['job_id']+(a or {})['analysis_id']+p['pair_id']):
                    selected.append(p['pair_id'])
        if len(selected)>4:
            st.warning('Select at most four pairs.')
        check_column,refresh_column=st.columns(2)
        if check_column.button('Check selected',type='primary',use_container_width=True,disabled=not selected or len(selected)>4):
            action(lambda:backend.verify_pairs(s['job_id'],selected,progress=None))
        if hasattr(backend,'refresh_verification') and refresh_column.button('Refresh evidence',use_container_width=True,disabled=not selected or len(selected)>4):
            action(lambda:backend.refresh_verification(s['job_id'],selected,progress=None))
        with st.expander('Other assessed pairs'):
            for p in (a or {}).get('pairs',[]):
                if p not in pairs:
                    st.text(p['relation'].replace('_',' ')+': '+p['explanation'])
    with evidence_tab:
        if s['mode']=='fixture':
            st.warning('Synthetic evidence — demonstration only. These sources are fictional and were not fetched.')
        if not v:
            st.info('No evidence checks yet. Select a potential disagreement to check it.')
        else:
            from .grounding import NATIVE_ATTRIBUTIONS
            for result in v['results']:
                st.subheader('Evidence assessment')
                st.caption(result['pair_id'])
                for column,verdict in zip(st.columns(2),result['verdicts']):
                    with column:
                        with st.container(border=True):
                            claim = claims[verdict['claim_id']]
                            st.caption(speakers[claim['speaker_id']])
                            st.text(claim['proposition'])
                            status = {'supported':'Supported by retrieved evidence','refuted':'Refuted by retrieved evidence'}.get(verdict['status'],verdict['status'].replace('_',' ').capitalize())
                            st.caption(status)
                            st.text(verdict['rationale'])
                st.text(result['summary'])
                attr = next((g for g in v['grounding_attributions'] if g['pair_id']==result['pair_id']),None)
                if attr and attr['search_entry_point_html']:
                    if digest(attr) in NATIVE_ATTRIBUTIONS:
                        import streamlit.components.v1 as components
                        components.html(attr['search_entry_point_html'],height=180,scrolling=True)
                    else:
                        st.warning('Live attribution requires a fresh native response. Imported Search HTML is preserved in JSON but is not rendered. Live display acceptance remains unresolved for saved results.')
                for e in v['evidence']:
                    if e['pair_id'] != result['pair_id']:
                        continue
                    with st.container(border=True):
                        st.text(e['title'])
                        st.caption({'grounded_summary':'Source-backed AI summary','metadata_only':'Source metadata only','retrieved_excerpt':'Retrieved source passage'}[e['content_origin']] if s['mode']!='fixture' else 'Synthetic evidence — demonstration only')
                        if e['content']:
                            st.text(e['content'])
                        st.caption(f"Publisher: {e['publisher'] or 'unknown'} · Published: {e['published_date'] or 'unknown'} · Retrieved: {e['retrieved_at']}")
                        normalize_url(e['url'])
                        st.link_button('Open source',e['url'])
            for issue in v['issues']:
                st.warning(', '.join(issue['related_ids'])+': '+issue['message'])
            for unverified in v['unverified']:
                st.caption(unverified['pair_id']+': '+unverified['reason'].replace('_',' '))
        st.divider()
        json_column,csv_column=st.columns(2)
        json_column.download_button('Download Snapshot JSON',snapshot_json(s),file_name='althea-snapshot.json',mime='application/json',use_container_width=True)
        csv_column.download_button('Download claims CSV',claims_csv(s),file_name='althea-claims.csv',mime='text/csv',use_container_width=True)
        st.caption('CSV text that could start a spreadsheet formula is escaped with an apostrophe. JSON preserves original text.')
        if hasattr(backend,'artifact_history'):
            with st.expander('Previous saved versions'):
                import json
                versions=backend.artifact_history(s['job_id'])
                if versions:
                    selected_version=st.selectbox('Saved version',list(range(len(versions))),format_func=lambda i:versions[i]['kind']+' · '+versions[i]['created_at'])
                    version=versions[selected_version]
                    st.download_button('Download saved version',(json.dumps(version['payload'],ensure_ascii=False,indent=2)+'\n').encode('utf-8'),file_name='althea-'+version['kind']+'-version.json',mime='application/json')
