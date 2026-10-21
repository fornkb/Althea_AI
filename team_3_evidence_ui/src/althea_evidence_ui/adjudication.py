import json
from importlib.resources import files
from ._contract import PairVerdict
from .runtime import VertexAdapter, usage
from .errors import ComponentError


class GoogleEvidenceJudge(VertexAdapter):
    mode = 'live'

    def judge(self, *, claims, pair, evidence, budget):
        from google.genai import types
        model = self.settings.get('text_model','gemini-2.5-flash')
        response, attempts = self.request('adjudication',budget,model=model,
            contents=json.dumps(dict(claims=claims,pair=pair,evidence=evidence),ensure_ascii=False),
            config=types.GenerateContentConfig(system_instruction=files(__package__).joinpath('prompts/adjudicate_v1.txt').read_text(encoding='utf-8'),
                response_mime_type='application/json',response_schema=PairVerdict,max_output_tokens=self.settings.get('max_output_tokens_adjudication',2048)))
        try:
            result = PairVerdict.model_validate_json(response.text).model_dump(mode='json')
        except (ValueError,TypeError) as exc:
            raise ComponentError('PROVIDER_RESPONSE_INVALID','Judge did not return a valid pair verdict.',stage='verification') from exc
        return result,[usage(response,'adjudication',model,attempts,provider=self.settings.get('provider','vertex'))]


class FixtureJudge:
    mode = 'fixture'

    def judge(self, *, claims, pair, evidence, budget):
        reference = json.loads(files(__package__).joinpath('data/verification.json').read_text(encoding='utf-8'))
        if pair['pair_id'] != 'pair_0001' or evidence != reference['evidence']:
            raise ComponentError('CONTRACT_INVALID','Synthetic verdicts require the original synthetic evidence.')
        return reference['results'][0],[]
