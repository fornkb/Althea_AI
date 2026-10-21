import json
from importlib.resources import files
from pathlib import Path
from ._contract import InputRequest
from .common import wire, validate_transcript, transcript_identity
from .audio import prepare_audio, beneath
from .transcription import GoogleCloudTranscriber, FixtureTranscriber, normalize_words
from .errors import ComponentError, require


class IngestionService:
    def __init__(self, settings: dict, *, transcriber=None):
        self.settings = dict(settings)
        require(self.settings.get('mode','fixture') in ('fixture','live'), 'Unknown mode.')
        self.transcriber = transcriber

    def ingest(self, source: dict, *, budget, progress=None) -> dict:
        request = wire(InputRequest, source)
        kind = request['kind']
        require((bool(request['sample_id']) and request['local_path'] is None) if kind == 'sample' else (bool(request['local_path']) and request['sample_id'] is None), 'Input path/sample fields disagree.', 'INVALID_INPUT')
        if kind == 'sample':
            require(request['sample_id'] == 'riverton_demo', 'Unknown sample.', 'INVALID_INPUT')
            t = json.loads(files(__package__).joinpath('data/transcript.json').read_text(encoding='utf-8'))
            t['source']['title'] = request['title']
            return validate_transcript(t)
        path = Path(request['local_path']).resolve()
        require(path.is_file(), 'Input must be an existing ordinary file.', 'INVALID_INPUT')
        if kind == 'transcript':
            try:
                require(path.stat().st_size <= 20*1024*1024, 'Transcript file exceeds 20 MiB.', 'INVALID_INPUT')
                t = validate_transcript(json.loads(path.read_text(encoding='utf-8-sig')))
            except (OSError, ValueError) as exc:
                raise ComponentError('INVALID_INPUT','Cannot read transcript JSON.') from exc
            if t['source']['audio_relpath'] is not None:
                beneath(self.settings['data_dir'],t['source']['audio_relpath'])
            t['source']['title'] = request['title']
            # Preserve fixture/human-reviewed provenance instead of claiming real speech.
            if t['origin'] == 'api':
                t['origin'] = 'imported'
            return t
        require(self.settings.get('mode') == 'live' or self.transcriber is not None and not isinstance(self.transcriber,FixtureTranscriber), 'Fixture mode offers a transcript sample only; arbitrary audio requires a live transcriber.', 'INVALID_INPUT')
        try:
            media = prepare_audio(path,self.settings)
            provider = self.transcriber or GoogleCloudTranscriber(self.settings)
            raw = provider.transcribe(media['path'],language='en',expected_speakers=2,budget=budget,progress=progress)
            speakers, segments = normalize_words(raw.get('words'))
            issues = []
            if len(speakers) != 2:
                issues.append(dict(stage='transcription',code='ONE_SPEAKER' if len(speakers)==1 else 'EXPERIMENTAL_ATTRIBUTION',message='One speaker detected.' if len(speakers)==1 else 'Attribution above two speakers is experimental; review it.',retryable=False,related_ids=[]))
            issues.extend(raw.get('issues',[]))
            t = dict(schema_version=self.settings.get('wire_schema_version','1.0.0'),transcript_id='pending',origin='api',language='en',duration_s=media['duration_s'],
                     source=dict(kind='audio',title=request['title'],**{k:media[k] for k in ('original_filename','content_sha256','audio_relpath')}),
                     speakers=speakers,segments=segments,issues=issues,usage=raw.get('usage',[]))
            t['transcript_id'] = transcript_identity(t)
            return validate_transcript(t)
        except OSError as exc:
            raise ComponentError('STORAGE_ERROR','Cannot read or store local audio.',stage='storage') from exc
