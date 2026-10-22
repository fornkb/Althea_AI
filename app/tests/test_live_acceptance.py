import json
import os
import time
from pathlib import Path
import pytest
from althea_app import LiveBackend,load_settings


@pytest.mark.live
def test_authorized_live_end_to_end():
    audio=os.getenv('ALTHEA_LIVE_AUDIO')
    if os.getenv('ALTHEA_RUN_E2E')!='1' or not os.getenv('GOOGLE_CLOUD_PROJECT') or not audio:
        pytest.skip('Set ALTHEA_RUN_E2E=1, GOOGLE_CLOUD_PROJECT, ADC, FFmpeg and ALTHEA_LIVE_AUDIO to an authorized real clip.')
    settings=load_settings('live')
    backend=LiveBackend(settings)
    start=time.monotonic()
    result=backend.run(dict(kind='audio',local_path=audio,sample_id=None,title='Authorized live acceptance'),verify=True)
    report=dict(status=result['status'],elapsed_s=time.monotonic()-start,job_id=result['job_id'],
        provider_attempts=backend.job_usage(result['job_id'])['attempts_used'],models={k:settings[k] for k in ('transcribe_model','text_model','grounding_model')},
        issues=result['issues'],human_accuracy_review='Pending: no automatic accuracy claim')
    report_path=Path('app/reports/live-e2e.json')
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    assert result['status']=='complete' and result['transcript']['origin']=='api'
