"""Persistent DashboardBackend connecting the three dictionary-only services."""
import copy
import hashlib
import json
import uuid
from pathlib import Path
from althea_ingestion import IngestionService,Repository,validate_transcript
from althea_ingestion.audio import beneath
from althea_ingestion.common import now,digest
from althea_analysis import AnalysisService,validate_analysis
from althea_evidence_ui import VerificationService,validate_verification
from althea_evidence_ui.grounding import NATIVE_ATTRIBUTIONS
from .settings import validate_settings
from .validation import validate_snapshot,eligible_pairs,requested_pairs
from .pipeline import empty_verification,merge_verification
from .budget import JobBudget
from .cache_keys import transcription_key,analysis_key,verification_key
from .locking import job_lock
from .errors import AppError,require,issue


class PersistentBackend:
    persistent = True

    def __init__(self,settings,*,transcriber=None,text_provider=None,retriever=None,judge=None,repository=None,recover=True):
        self.settings=validate_settings(settings)
        self.mode=self.settings['mode']
        root=Path(self.settings['data_dir']);root.mkdir(parents=True,exist_ok=True)
        db_name='live-gemini.sqlite' if self.mode=='live' and self.settings['provider']=='gemini' else self.mode+'.sqlite'
        self.repository=repository or Repository(str(root/db_name))
        self.repository.initialize()
        self.ingestion=IngestionService(self.settings,transcriber=transcriber)
        self.analysis=AnalysisService(self.settings,text_provider=text_provider)
        self.verification=VerificationService(self.settings,retriever=retriever,judge=judge)
        self._session_attempts={}
        self._activity={}
        if recover:
            self.recover_interrupted()

    def _lock(self,job_id):
        return job_lock(self.settings['data_dir'],self.mode+'-'+self.settings['provider'],job_id)

    def _save(self,s):
        s['updated_at']=now()
        s=validate_snapshot(s)
        self.repository.save_snapshot(s)
        return s

    def _event(self,job_id,code,message,related_ids=None):
        self.repository.append_event(job_id,issue(code,message,related_ids=related_ids))

    def _cache_hit(self,job_id,stage):
        self._activity.setdefault(job_id,dict(cache_hits=[],new_attempts=0))['cache_hits'].append(stage)
        self._event(job_id,'CACHE_HIT','Reused validated historical result without a new provider attempt.',[stage])

    def _finish(self,job_id,budget):
        self._session_attempts[job_id]=self._session_attempts.get(job_id,0)+budget.new_attempts
        self._activity.setdefault(job_id,dict(cache_hits=[]))['new_attempts']=budget.new_attempts

    def _start_activity(self,job_id):
        self._activity[job_id]=dict(cache_hits=[],new_attempts=0)
        return JobBudget(self.repository,job_id,self.settings['max_provider_attempts'])

    def _failure(self,s,exc,stage,budget):
        budget.finish(False)
        codes={'MISSING_AUDIO_TOOLS':'FFMPEG_MISSING','JOB_NOT_FOUND':'NOT_FOUND'}
        code=codes.get(getattr(exc,'code',''),getattr(exc,'code','PROVIDER_UNAVAILABLE'))
        message=str(exc) if getattr(exc,'code',None) else 'This stage could not finish. Check the local setup and provider configuration.'
        error=issue(code,message,stage=stage,related_ids=[s['job_id']],retryable=bool(getattr(exc,'retryable',False)))
        s.update(status='partial' if stage=='verification' and s['analysis'] is not None else 'failed',issues=[error])
        self.repository.append_event(s['job_id'],error)
        return self._save(s)

    def _source(self,source):
        require(isinstance(source,dict) and set(source)=={'kind','local_path','sample_id','title'},'Input requires kind, local_path, sample_id and title.','INVALID_INPUT')
        require(source['kind'] in ('audio','transcript','sample') and isinstance(source['title'],str) and bool(source['title'].strip()),'Choose a valid input and title.','INVALID_INPUT')
        if source['kind']=='sample':
            require(source['sample_id']=='riverton_demo' and source['local_path'] is None,'Unknown sample.','INVALID_INPUT')
            require(self.mode=='fixture','Choose Sample demo mode for the fictional sample.','INVALID_INPUT')
        else:
            require(isinstance(source['local_path'],str) and bool(source['local_path']) and source['sample_id'] is None,'Choose a local input file.','INVALID_INPUT')
            require(self.mode=='live','Arbitrary files require Live analysis mode; the sample never pretends to process them.','INVALID_INPUT')
        return dict(source)

    def _transcript(self,source,s,budget,progress):
        cache_key=None
        if source['kind']=='audio':
            path=Path(source['local_path']).resolve()
            require(path.is_file() and path.suffix.lower() in ('.mp3','.wav'),'Choose an existing MP3 or WAV file.','INVALID_INPUT')
            require(0<path.stat().st_size<=self.settings['max_upload_bytes'],'Audio exceeds the configured upload limit.','AUDIO_TOO_LARGE')
            raw=path.read_bytes()
            require(len(raw)<=self.settings['max_upload_bytes'],'Audio changed during validation.','AUDIO_TOO_LARGE')
            source_hash=hashlib.sha256(raw).hexdigest()
            cache_key=transcription_key(self.settings,source_hash)
            cached=self.repository.get_cached(cache_key)
            if cached is not None:
                t=validate_transcript(cached)
                require(t['source']['content_sha256']==source_hash and t['source']['kind']=='audio' and t['origin']=='api','Invalid cached transcription provenance.')
                require(t['source']['audio_relpath'] is not None and Path(t['source']['audio_relpath']).suffix.lower()==path.suffix.lower(),'Audio extension disagrees with the previously validated media format.','INVALID_INPUT')
                require(t['duration_s']<=self.settings['max_audio_seconds'],'Audio exceeds the configured duration limit.','AUDIO_TOO_LONG')
                if t['source']['audio_relpath']:
                    media=beneath(self.settings['data_dir'],t['source']['audio_relpath'])
                    media.parent.mkdir(parents=True,exist_ok=True)
                    try:
                        with media.open('xb') as handle:handle.write(raw)
                    except FileExistsError:
                        require(hashlib.sha256(media.read_bytes()).hexdigest()==source_hash,'Stored original media differs from its content hash.','STORAGE_ERROR')
                t['source'].update(title=source['title'],original_filename=self._original_filename(path))
                self._cache_hit(s['job_id'],'transcription')
                return t
        t=self.ingestion.ingest(source,budget=budget,progress=progress)
        budget.finish(True)
        t=validate_transcript(t)
        if cache_key:
            require(t['source']['content_sha256']==source_hash,'Upload content changed before transcription completed.')
            t['source']['original_filename']=self._original_filename(path)
            self.repository.put_cached(cache_key,t)
        return t

    def _original_filename(self,path):
        uploads=(Path(self.settings['data_dir'])/'uploads').resolve()
        if path.parent==uploads:
            metadata=path.with_suffix('.upload.json')
            if metadata.is_file() and metadata.stat().st_size<=4096:
                try:
                    name=json.loads(metadata.read_text(encoding='utf-8')).get('original_filename')
                    if isinstance(name,str) and 0<len(name)<=512:return name
                except (ValueError,OSError,AttributeError):
                    pass
        return path.name

    def _analysis(self,s,budget,progress):
        t=validate_transcript(s['transcript'])
        key=analysis_key(self.settings,t['transcript_id'])
        a=self.repository.get_cached(key)
        if a is None:
            a=self.analysis.analyze(t,budget=budget,progress=progress)
            budget.finish(True)
            a=validate_analysis(a,t)
            self.repository.put_cached(key,a)
        else:
            a=validate_analysis(a,t)
            self._cache_hit(s['job_id'],'analysis')
        s.update(analysis=a,verification=None)
        return self._save(s)

    def _remember_native(self,job_id,v):
        for attr in v['grounding_attributions']:
            identity=digest(attr)
            if identity in NATIVE_ATTRIBUTIONS:
                self._event(job_id,'NATIVE_GROUNDING','Native provider attribution observed; HTML itself is stored only in its artifact.',[identity,v['analysis_id']])

    def _restore_native(self,v):
        if v and v['grounding_attributions']:
            trusted=self.repository.native_attribution_hashes()
            for attr in v['grounding_attributions']:
                identity=digest(attr)
                if identity in trusted:
                    NATIVE_ATTRIBUTIONS.add(identity)

    def _verify(self,s,pair_ids,budget,progress,*,refresh=False):
        a=validate_analysis(s['analysis'],s['transcript'])
        requested_pairs(a,pair_ids,self.settings['max_verify_pairs'])
        previous=s['verification']
        if previous is None or previous['analysis_id']!=a['analysis_id']:
            previous=empty_verification(a)
        tokens=[a['analysis_id']+':'+p for p in pair_ids]
        allowed_tokens=self.repository.reserve_verification_pairs(s['job_id'],tokens,self.settings['max_verify_pairs'])
        allowed={token.split(':',1)[1] for token in allowed_tokens}
        blocked=set(pair_ids)-allowed
        if refresh:
            for p in pair_ids:
                self.repository.delete_cached(verification_key(self.settings,a['analysis_id'],p))
            previous=merge_verification(a,previous,empty_verification(a),touched=pair_ids,refresh=True,blocked=blocked)
        s.update(status='running',verification=previous)
        self._save(s)
        merged=merge_verification(a,previous,empty_verification(a),touched=[],blocked=blocked)
        for p in pair_ids:
            if p not in allowed:
                continue
            key=verification_key(self.settings,a['analysis_id'],p)
            fresh=None if refresh else self.repository.get_cached(key)
            if fresh is not None:
                fresh=validate_verification(fresh,a)
                require(p in {r['pair_id'] for r in fresh['results']},'Cached pair does not contain its requested result.')
                self._restore_native(fresh)
                self._cache_hit(s['job_id'],'evidence '+p)
                if p in {r['pair_id'] for r in merged['results']}:
                    # Reading the same cached artifact is not another execution.
                    fresh=copy.deepcopy(fresh)
                    fresh['usage']=[]
            else:
                fresh=self.verification.verify(s['transcript'],a,[p],budget=budget,progress=progress)
                fresh=validate_verification(fresh,a)
                success=p in {r['pair_id'] for r in fresh['results']}
                budget.finish(success)
                if success:
                    self._remember_native(s['job_id'],fresh)
                    self.repository.put_cached(key,fresh)
            merged=merge_verification(a,merged,fresh,touched=[p],refresh=refresh)
            s['verification']=merged
            self._save(s)  # retain each completed pair even if a later pair is interrupted
        s['verification']=merged
        failed=any(u['reason']!='not_selected' for u in merged['unverified']) or bool(merged['issues'])
        s['status']='partial' if failed else 'complete'
        return self._save(s)

    def run(self,source,*,verify,progress=None):
        source=self._source(source)
        job_id=str(uuid.uuid4())
        stamp=now()
        s=dict(schema_version=self.settings['wire_schema_version'],job_id=job_id,title=source['title'],mode=self.mode,status='running',created_at=stamp,updated_at=stamp,transcript=None,analysis=None,verification=None,issues=[])
        with self._lock(job_id):
            self._save(s)
            budget=self._start_activity(job_id)
            stage='input'
            try:
                if progress:progress('Preparing transcript')
                stage='transcription' if source['kind']=='audio' else 'input'
                s['transcript']=self._transcript(source,s,budget,progress)
                self._save(s)
                stage='analysis'
                s=self._analysis(s,budget,progress)
                if verify:
                    stage='verification'
                    selected=sorted(eligible_pairs(s['analysis']).values(),key=lambda p:(p['priority'],p['pair_id']))[:self.settings['max_verify_pairs']]
                    s=self._verify(s,[p['pair_id'] for p in selected],budget,progress)
                else:
                    s['status']='complete';s=self._save(s)
            except Exception as exc:
                s=self._failure(s,exc,stage,budget)
            finally:
                self._finish(job_id,budget)
            return copy.deepcopy(s)

    def load(self,job_id):
        s=validate_snapshot(self.repository.load_snapshot(job_id))
        require(s['mode']==self.mode,'This job belongs to another mode.')
        self._restore_native(s['verification'])
        return s

    def list_jobs(self,limit=20):
        return [s for s in self.repository.list_jobs(limit) if s['mode']==self.mode]

    def save_review(self,job_id,transcript):
        with self._lock(job_id):
            before=self.load(job_id)
            s=self.repository.review_transcript(job_id,transcript)
            if before['transcript']['transcript_id']!=s['transcript']['transcript_id']:
                s['issues']=[];s=self._save(s)
                self._event(job_id,'TRANSCRIPT_REVIEWED','Human review cleared active analysis and evidence.')
            return s

    def reanalyze(self,job_id,*,verify,progress=None):
        with self._lock(job_id):
            s=self.load(job_id)
            require(s['transcript'] is not None,'No saved transcript to analyze.')
            if self.mode=='fixture':
                original=self.ingestion.ingest(dict(kind='sample',local_path=None,sample_id='riverton_demo',title=s['title']),budget=None)
                if s['transcript']['transcript_id']!=original['transcript_id']:
                    s.update(status='ready',analysis=None,verification=None,issues=[issue('CUSTOM_EDIT_REQUIRES_LIVE','Custom edited analysis requires live backend. Your reviewed transcript is saved.')])
                    return self._save(s)
            s.update(status='running',analysis=None,verification=None,issues=[])
            self._save(s)
            budget=self._start_activity(job_id)
            stage='analysis'
            try:
                s=self._analysis(s,budget,progress)
                if verify:
                    stage='verification'
                    pairs=sorted(eligible_pairs(s['analysis']).values(),key=lambda p:(p['priority'],p['pair_id']))[:self.settings['max_verify_pairs']]
                    s=self._verify(s,[p['pair_id'] for p in pairs],budget,progress)
                else:
                    s['status']='complete';s=self._save(s)
            except Exception as exc:
                s=self._failure(s,exc,stage,budget)
            finally:
                self._finish(job_id,budget)
            return copy.deepcopy(s)

    def _verify_action(self,job_id,pair_ids,progress,refresh):
        with self._lock(job_id):
            s=self.load(job_id)
            require(s['analysis'] is not None,'Reanalyze the saved transcript before checking evidence.')
            requested_pairs(s['analysis'],pair_ids,self.settings['max_verify_pairs'])
            budget=self._start_activity(job_id)
            try:
                s=self._verify(s,pair_ids,budget,progress,refresh=refresh)
            except Exception as exc:
                # On refresh, use the latest persisted version, where selected old results were cleared.
                s=self.load(job_id)
                s=self._failure(s,exc,'verification',budget)
            finally:
                self._finish(job_id,budget)
            return copy.deepcopy(s)

    def verify_pairs(self,job_id,pair_ids,*,progress=None):
        return self._verify_action(job_id,pair_ids,progress,False)

    def refresh_verification(self,job_id,pair_ids,progress=None):
        return self._verify_action(job_id,pair_ids,progress,True)

    def job_usage(self,job_id):
        return {**self.repository.job_metrics(job_id),'attempt_limit':self.settings['max_provider_attempts'],'pair_limit':self.settings['max_verify_pairs'],
            'new_attempts_this_action':self._activity.get(job_id,{}).get('new_attempts',0),'attempts_this_session':self._session_attempts.get(job_id,0),
            'cache_hits':list(self._activity.get(job_id,{}).get('cache_hits',[]))}

    def artifact_history(self,job_id):
        self.load(job_id)
        return self.repository.artifact_history(job_id)

    def recover_interrupted(self):
        recovered=[]
        for job in self.repository.running_jobs():
            if job['mode']!=self.mode:continue
            try:
                with self._lock(job['job_id']):
                    s=self.load(job['job_id'])
                    if s['status']!='running':continue
                    s['status']='partial' if s['analysis'] is not None else 'failed'
                    s['issues'].append(issue('INTERRUPTED','A previous run stopped before completion. Saved work is retained; no provider requests were resumed.'))
                    self._save(s)
                    self._event(s['job_id'],'INTERRUPTED','Interrupted job recovered without provider requests.')
                    recovered.append(s['job_id'])
            except AppError as exc:
                if exc.code!='JOB_BUSY':raise
        return recovered


class LiveBackend(PersistentBackend):
    def __init__(self,settings,**kwargs):
        super().__init__({**settings,'mode':'live','provider':'vertex','api_key':None},**kwargs)


class SampleBackend(PersistentBackend):
    def __init__(self,settings,**kwargs):
        super().__init__({**settings,'mode':'fixture','provider':'vertex','api_key':None},**kwargs)


class GeminiBackend(PersistentBackend):
    requires_api_key=True

    def __init__(self,settings,**kwargs):
        from .gemini_audio import GeminiAudioTranscriber
        s=validate_settings({**settings,'mode':'live','provider':'gemini','transcribe_model':settings.get('gemini_audio_model','gemini-2.5-flash')})
        if kwargs.get('transcriber') is None:kwargs['transcriber']=GeminiAudioTranscriber(s)
        super().__init__(s,**kwargs)

    def configure_api_key(self,key):
        from .gemini_audio import GeminiAudioTranscriber
        self.settings=validate_settings({**self.settings,'api_key':key or None})
        self.ingestion=IngestionService(self.settings,transcriber=GeminiAudioTranscriber(self.settings))
        self.analysis=AnalysisService(self.settings)
        self.verification=VerificationService(self.settings)
