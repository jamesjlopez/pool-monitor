"""Exercise shared maintenance persistence through the real HTTP handler."""
import json
import threading
from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from uuid import uuid4

import pytest

from monitor.dashboard_server import DashboardHandler


@pytest.fixture
def dashboard(tmp_path):
    class Handler(DashboardHandler):
        maintenance_path = tmp_path / 'maintenance.json'

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port, Handler.maintenance_path
    server.shutdown()
    server.server_close()
    thread.join()


def request(dashboard, method='GET', value=None, **headers):
    connection = HTTPConnection('127.0.0.1', dashboard[0])
    connection.request(method, '/api/maintenance', json.dumps(value) if value is not None else None,
                       {'Content-Type': 'application/json', **headers})
    response = connection.getresponse()
    result = response.status, json.loads(response.read())
    connection.close()
    return result


def event(kind='surface_skimmer'):
    return {'id': str(uuid4()), 'ts': '2026-09-20T12:07:00-05:00', 'kind': kind,
            'notes': 'Basket full of leaves'}


def test_persists_types_time_notes_and_retries_without_duplicates(dashboard):
    assert request(dashboard) == (200, [])
    entries = [event(kind) for kind in ['filter_element', 'filter_canister', 'surface_skimmer', 'pump_basket']]
    for entry in entries:
        assert request(dashboard, 'POST', entry)[0] == 200
        assert request(dashboard, 'POST', entry)[0] == 200
    status, records = request(dashboard)
    assert status == 200 and len(records) == 4
    assert records[0]['ts'] == '2026-09-20T17:07:00+00:00'
    assert records[0]['notes'] == 'Basket full of leaves'
    assert json.loads(dashboard[1].read_text()) == records
    entries[0]['notes'] = 'different'
    assert request(dashboard, 'POST', entries[0])[0] == 409


@pytest.mark.parametrize('field,value', [('kind','unknown'), ('ts','2099-01-01T00:00:00Z'),
    ('ts','2026-01-01T00:00:00'), ('id','bad'), ('notes','a' * 1001)])
def test_invalid_record_is_not_written(dashboard, field, value):
    entry = event()
    entry[field] = value
    assert request(dashboard, 'POST', entry)[0] == 400
    assert not dashboard[1].exists()


def test_cross_origin_and_form_posts_rejected(dashboard):
    assert request(dashboard, 'POST', event(), Origin='https://unrelated.example')[0] == 403
    assert request(dashboard, 'POST', event(), **{'Content-Type': 'text/plain'})[0] == 415
    assert not dashboard[1].exists()


def test_corrupt_history_is_preserved(dashboard):
    dashboard[1].write_text('broken')
    assert request(dashboard)[0] == 500
    assert request(dashboard, 'POST', event())[0] == 500
    assert dashboard[1].read_text() == 'broken'
