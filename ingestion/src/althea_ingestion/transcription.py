"""Provider output is {'words': [{word,speaker,start_s,end_s}], 'usage': [...]}.

Injected providers own attempt accounting, just as the live adapter does.
Word spelling/order, including punctuation, is retained; only separating spaces
are inserted when word annotations lack whitespace.
"""
import json
from importlib.resources import files
from pathlib import Path
from .errors import ComponentError, require
from .runtime import VertexAdapter, usage


def seconds(value):
    if isinstance(value, (int,float)) and not isinstance(value,bool):
        return float(value)
    if isinstance(value,str) and value.endswith('s'):
        return float(value[:-1])
    if hasattr(value,'total_seconds'):
        return value.total_seconds()
    raise ComponentError('PROVIDER_RESPONSE_INVALID','Provider word timestamps are missing or unsupported.',stage='transcription')


def normalize_words(words):
    require(isinstance(words,list) and bool(words), 'No usable timed speech was returned.', 'PROVIDER_RESPONSE_INVALID')
    speakers, turns = {}, []
    previous = -1
    for word in words:
        try:
            speaker, text = word['speaker'], word['word']
            start, end = round(seconds(word['start_s']),3), round(seconds(word['end_s']),3)
        except (KeyError, TypeError, ValueError) as exc:
            raise ComponentError('PROVIDER_RESPONSE_INVALID','Incomplete word/speaker/timing annotations.',stage='transcription') from exc
        require(speaker is not None and str(speaker).strip() and str(speaker).upper() != 'UNKNOWN', 'Speakerless speech requires review; labels cannot be invented.', 'PROVIDER_RESPONSE_INVALID')
        require(isinstance(text,str) and bool(text.strip()) and previous <= start < end, 'Invalid word order/timing.', 'PROVIDER_RESPONSE_INVALID')
        key = str(speaker)
        if key not in speakers:
            speakers[key] = f'speaker_{len(speakers)+1:02d}'
        sid = speakers[key]
        if turns and turns[-1]['speaker_id'] == sid and start - turns[-1]['end_s'] <= 1.0:
            turn = turns[-1]
            separator = '' if turn['text'].endswith((' ','\n','\t')) or text.startswith((' ','\n','\t',',','.','!','?',':',';')) else ' '
            turn['text'] += separator + text
            turn['end_s'] = max(turn['end_s'],end)
        else:
            turns.append(dict(segment_id=f'seg_{len(turns)+1:04d}',speaker_id=sid,start_s=start,end_s=end,text=text))
        previous = start
    require(len(speakers) <= 4, 'This demo supports at most four speakers.', 'PROVIDER_RESPONSE_INVALID')
    return [dict(speaker_id=s,display_name=f'Speaker {i}') for i,s in enumerate(speakers.values(),1)], turns


class FixtureTranscriber:
    """Explicit fake for tests; ingest() refuses arbitrary fixture-mode audio."""
    mode = 'fixture'

    def transcribe(self, audio_path, *, language, expected_speakers, budget, progress=None, duration_s=None):
        t = json.loads(files(__package__).joinpath('data/transcript.json').read_text(encoding='utf-8'))
        return dict(words=[dict(word=s['text'],speaker=s['speaker_id'],start_s=s['start_s'],end_s=s['end_s']) for s in t['segments']], usage=[])


class GoogleCloudTranscriber(VertexAdapter):
    mode = 'live'

    def transcribe(self, audio_path: str, *, language: str, expected_speakers: int, budget, progress=None, duration_s=None):
        from google.genai import types
        try:
            config = types.GenerateContentConfig(audio_transcription_config=types.AudioTranscriptionConfig(
                word_timestamp=True,diarization=True,language_codes=['en-US'],mode='VERBATIM'))
        except (AttributeError,ValueError) as exc:
            raise ComponentError('PROVIDER_UNAVAILABLE','Installed google-genai lacks verbatim diarization/timestamp support; install a compatible SDK.',stage='transcription') from exc
        model = self.settings.get('transcribe_model','gemini-3.5-transcribe')
        path = Path(audio_path)
        if progress:
            progress('Requesting English verbatim transcription with speaker and word timing annotations.')
        response, attempts = self.request('transcription',budget, model=model,
            contents=[types.Part.from_bytes(data=path.read_bytes(),mime_type='audio/mpeg' if path.suffix.lower()=='.mp3' else 'audio/wav')],config=config)
        parts = getattr(response,'parts',None)
        if parts is None:
            candidates = getattr(response,'candidates',[]) or []
            parts = getattr(getattr(candidates[0],'content',None),'parts',[]) if candidates else []
        words = []
        for part in parts or []:
            tx = getattr(part,'audio_transcription',None)
            for w in getattr(tx,'words',[]) or []:
                speaker = getattr(w,'speaker_label',None)
                if speaker is None:
                    speaker = getattr(tx,'speaker_label',None)
                words.append(dict(word=getattr(w,'word',None),speaker=speaker,
                                  start_s=seconds(getattr(w,'start_offset',None)),end_s=seconds(getattr(w,'end_offset',None))))
        require(bool(words), 'Transcription returned no speaker-labelled word timestamps. No timings were fabricated.', 'PROVIDER_RESPONSE_INVALID')
        return dict(words=words,usage=[usage(response,'transcription',model,attempts)])
