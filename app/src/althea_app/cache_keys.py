"""Content/configuration keys; titles, paths and remaining budgets are excluded."""
import hashlib
from importlib.resources import files
from althea_ingestion.common import digest
from althea_analysis import EXTRACTION_VERSION,COMPARISON_VERSION,NORMALIZATION_VERSION,MATCHING_VERSION
from althea_evidence_ui.verification import RETRIEVAL_VERSION,ADJUDICATION_VERSION

TRANSCRIPTION_VERSION = 'verbatim-word-turns-v1.0.0'
EVIDENCE_FORMAT_VERSION = 'native-grounding-v1.0.0'


def prompt_hash(package, name):
    return hashlib.sha256(files(package).joinpath('prompts',name).read_bytes()).hexdigest()


def key(stage, settings, payload):
    return stage+':'+digest(dict(stage=stage,mode=settings['mode'],provider=settings.get('provider','vertex'),schema=settings.get('wire_schema_version','1.0.0'),location=settings['location'],**payload))


def transcription_key(settings, source_hash):
    from .gemini_audio import TRANSCRIPTION_PROMPT
    return key('transcription',settings,dict(source_hash=source_hash,language='en',model=settings['transcribe_model'],
        prompt_hash=hashlib.sha256(TRANSCRIPTION_PROMPT.encode('utf-8')).hexdigest() if settings.get('provider')=='gemini' else None,
        normalization=settings.get('transcription_version','gemini-model-turns-v1.0.0' if settings.get('provider')=='gemini' else TRANSCRIPTION_VERSION),config=dict(verbatim=True,word_timestamp=settings.get('provider')!='gemini',diarization=True,language_codes=['en-US'],expected_speakers=2)))


def analysis_key(settings, transcript_id):
    return key('analysis',settings,dict(transcript_id=transcript_id,model=settings['text_model'],
        extraction=settings.get('extraction_version',EXTRACTION_VERSION),comparison=settings.get('comparison_version',COMPARISON_VERSION),
        normalization=settings.get('normalization_version',NORMALIZATION_VERSION),matching=settings.get('matching_version',MATCHING_VERSION),
        prompt_hashes=[prompt_hash('althea_analysis','extract_v1.txt'),prompt_hash('althea_analysis','compare_v1.txt')],
        max_claims=settings['max_claims'],max_pairs=settings['max_candidate_pairs'],
        extraction_tokens=settings['max_output_tokens_extraction'],comparison_tokens=settings['max_output_tokens_comparison']))


def verification_key(settings, analysis_id, pair_id):
    return key('verification',settings,dict(analysis_id=analysis_id,pair_id=pair_id,grounding_model=settings['grounding_model'],judge_model=settings['text_model'],
        retrieval=settings.get('retrieval_version',RETRIEVAL_VERSION),adjudication=settings.get('adjudication_version',ADJUDICATION_VERSION),
        format=settings.get('evidence_format_version',EVIDENCE_FORMAT_VERSION),
        prompt_hashes=[prompt_hash('althea_evidence_ui','retrieve_v1.txt'),prompt_hash('althea_evidence_ui','adjudicate_v1.txt')],
        retrieval_tokens=settings['max_output_tokens_retrieval'],adjudication_tokens=settings['max_output_tokens_adjudication']))
