from althea_app import LiveBackend,SampleBackend,GeminiBackend,load_settings
from althea_evidence_ui import render_app


if __name__=='__main__':
    # The live factory constructs no cloud clients until the user requests work.
    render_app({'Sample demo':lambda:SampleBackend(load_settings('fixture',overrides={'provider':'vertex'})),
                'Gemini API key':lambda:GeminiBackend(load_settings('live')),
                'Live analysis':lambda:LiveBackend(load_settings('live',overrides={'provider':'vertex'}))})
