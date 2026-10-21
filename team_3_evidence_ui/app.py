from althea_evidence_ui import render_app, FixtureBackend

if __name__ == '__main__':
    render_app({'Sample demo': lambda: FixtureBackend()})
