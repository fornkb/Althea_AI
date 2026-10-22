"""Only native source-index mappings can produce source-backed summaries."""
import json
from importlib.resources import files
from .common import normalize_url, now, digest
from .runtime import VertexAdapter, usage
from .errors import ComponentError, require

# Native metadata observed in this process, never arbitrary imported HTML.
NATIVE_ATTRIBUTIONS = set()


def parse_grounding(metadata, text, pair, claims):
    chunks = metadata.get('grounding_chunks') or []
    supports = metadata.get('grounding_supports') or []
    mapped = {}
    for support in supports:
        segment = support.get('segment') or {}
        passage = segment.get('text')
        if not isinstance(passage,str) or not passage.strip() or passage not in text:
            continue
        for index in support.get('grounding_chunk_indices') or []:
            if type(index) is int and 0 <= index < len(chunks):
                mapped.setdefault(index,[]).append(passage)
    sources = {}
    for index, chunk in enumerate(chunks):
        web = chunk.get('web') or {}
        url = web.get('uri')
        if not isinstance(url,str):
            continue
        try:
            normalized = normalize_url(url)
        except ComponentError:
            continue
        source = sources.setdefault(normalized,dict(url=url,title=web.get('title') or url,passages=[]))
        for passage in mapped.get(index,[]):
            if passage not in source['passages']:
                source['passages'].append(passage)
    evidence = []
    for i, (_, s) in enumerate(sorted(sources.items()),1):
        evidence.append(dict(evidence_id=f'ev_{pair["pair_id"]}_{i:04d}',pair_id=pair['pair_id'],claim_ids=[c['claim_id'] for c in claims],
            url=s['url'],title=s['title'],publisher=None,published_date=None,retrieved_at=now(),content='\n'.join(s['passages']) or None,
            content_origin='grounded_summary' if s['passages'] else 'metadata_only',queries=metadata.get('web_search_queries') or []))
    html = (metadata.get('search_entry_point') or {}).get('rendered_content')
    attribution = dict(pair_id=pair['pair_id'],search_entry_point_html=html) if html else None
    return evidence, attribution


class GoogleGroundedRetriever(VertexAdapter):
    mode = 'live'

    def retrieve(self, *, transcript, claims, pair, budget):
        from google.genai import types
        model = self.settings.get('grounding_model','gemini-2.5-flash')
        system = files(__package__).joinpath('prompts/retrieve_v1.txt').read_text(encoding='utf-8')
        cited={span['segment_id'] for claim in claims for span in claim['source_spans']}
        positions={i for i,segment in enumerate(transcript['segments']) if segment['segment_id'] in cited}
        context=[segment for i,segment in enumerate(transcript['segments']) if any(abs(i-j)<=1 for j in positions)]
        response, attempts = self.request('retrieval',budget,model=model,contents=json.dumps({'claims':claims,'comparison':pair,
            'conversation_title':transcript['source']['title'],'context_segments':context},ensure_ascii=False),
            config=types.GenerateContentConfig(system_instruction=system,tools=[types.Tool(google_search=types.GoogleSearch())],max_output_tokens=self.settings.get('max_output_tokens_retrieval',2048)))
        candidates = getattr(response,'candidates',None) or []
        if not candidates:
            raise ComponentError('PROVIDER_RESPONSE_INVALID','Grounded response had no candidate.',stage='verification')
        native = getattr(candidates[0],'grounding_metadata',None)
        metadata = native.model_dump(mode='json',exclude_none=True) if native is not None else {}
        evidence, attribution = parse_grounding(metadata,response.text or '',pair,claims)
        if attribution:
            NATIVE_ATTRIBUTIONS.add(digest(attribution))
        return evidence,[usage(response,'retrieval',model,attempts,provider=self.settings.get('provider','vertex'))],attribution


class FixtureRetriever:
    mode = 'fixture'

    def retrieve(self, *, transcript, claims, pair, budget):
        reference = json.loads(files(__package__).joinpath('data/reference_snapshot.json').read_text(encoding='utf-8'))
        expected = [c for c in reference['analysis']['claims'] if c['claim_id'] in (pair['claim_a_id'],pair['claim_b_id'])]
        reference_pair = reference['analysis']['pairs'][0]
        semantic_keys = ('pair_id','claim_a_id','claim_b_id','relation','numeric_difference','numeric_difference_unit')
        require(transcript['transcript_id'] == reference['transcript']['transcript_id'] and claims == expected and all(pair[k]==reference_pair[k] for k in semantic_keys), 'Synthetic verification supports the original Riverton pair only.')
        return reference['verification']['evidence'],[],None
