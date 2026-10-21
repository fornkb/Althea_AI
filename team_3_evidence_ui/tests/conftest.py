import json
import socket
from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch,request):
    if request.node.get_closest_marker('live'):
        return
    def blocked(*a,**k):
        raise AssertionError('Network is forbidden in offline tests')
    monkeypatch.setattr(socket,'create_connection',blocked)
    monkeypatch.setattr(socket.socket,'connect',blocked)


@pytest.fixture
def snapshot():
    return json.loads((Path(__file__).parents[1]/'fixtures/reference_snapshot.json').read_text(encoding='utf-8'))
