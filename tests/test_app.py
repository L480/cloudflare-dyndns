"""Tests for the FRITZ!Box facing DynDNS endpoint."""

import base64
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as dyndns  # noqa: E402

TOKEN = 'test-token'
ZONE = SimpleNamespace(id='zone-id', name='example.com')


def make_record(record_type, content, record_id='record-id',
                name='www.example.com'):
    return SimpleNamespace(id=record_id, name=name, type=record_type,
                           content=content, ttl=1, proxied=False)


class FakeClient:
    """Minimal stand-in for cloudflare.Cloudflare."""

    def __init__(self, zones=(ZONE,), records=()):
        self._zones = list(zones)
        self._records = list(records)
        self.edits = []

        self.zones = SimpleNamespace(list=self._list_zones)
        self.dns = SimpleNamespace(
            records=SimpleNamespace(list=self._list_records, edit=self._edit))

    def _list_zones(self, name=None, per_page=None):
        return _Page([z for z in self._zones
                      if name is None or z.name == name])

    def _list_records(self, zone_id=None, type=None, name=None, match=None):
        wanted = name['exact'] if isinstance(name, dict) else name
        return _Page([r for r in self._records
                      if r.type == type and r.name == wanted])

    def _edit(self, record_id, **payload):
        self.edits.append((record_id, payload))
        return SimpleNamespace(id=record_id, **payload)


class _Page(list):
    """Pagination object: iterable and exposing .result like the real SDK."""

    @property
    def result(self):
        return list(self)


@pytest.fixture
def client():
    return dyndns.app.test_client()


@pytest.fixture
def cloudflare_client():
    fake = FakeClient(records=[make_record('A', '1.2.3.4'),
                               make_record('AAAA', '2001:db8::1')])
    with mock.patch.object(dyndns, 'Cloudflare', return_value=fake):
        yield fake


def get(client, **params):
    params.setdefault('token', TOKEN)
    return client.get('/', query_string=params)


def test_healthz(client):
    response = client.get('/healthz')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'


def test_updates_a_record_and_answers_dyndns2(client, cloudflare_client):
    response = get(client, zone='example.com', record='www', ipv4='9.9.9.9')

    assert response.status_code == 200
    assert response.mimetype == 'text/plain'
    assert response.get_data(as_text=True).strip() == 'good 9.9.9.9'

    record_id, payload = cloudflare_client.edits[0]
    assert record_id == 'record-id'
    assert payload == {'zone_id': 'zone-id', 'type': 'A',
                       'name': 'www.example.com', 'content': '9.9.9.9',
                       'ttl': 1, 'proxied': False}


def test_unchanged_address_answers_nochg(client, cloudflare_client):
    response = get(client, zone='example.com', record='www', ipv4='1.2.3.4')

    assert response.get_data(as_text=True).strip() == 'nochg 1.2.3.4'
    assert cloudflare_client.edits == []


def test_updates_both_records(client, cloudflare_client):
    response = get(client, zone='example.com', record='www', ipv4='9.9.9.9',
                   ipv6='2001:db8::99')

    assert response.status_code == 200
    assert [payload['type'] for _, payload in cloudflare_client.edits] == \
        ['A', 'AAAA']


def test_zone_apex_without_record(client):
    fake = FakeClient(records=[make_record('A', '1.2.3.4',
                                           name='example.com')])
    with mock.patch.object(dyndns, 'Cloudflare', return_value=fake):
        response = get(client, zone='example.com', ipv4='9.9.9.9')

    assert response.get_data(as_text=True).strip() == 'good 9.9.9.9'


def test_domain_parameter_resolves_zone(client, cloudflare_client):
    response = get(client, domain='www.example.com.', ipv4='9.9.9.9')

    assert response.get_data(as_text=True).strip() == 'good 9.9.9.9'
    assert cloudflare_client.edits[0][1]['zone_id'] == 'zone-id'


def test_domain_outside_account_is_nohost(client, cloudflare_client):
    response = get(client, domain='www.example.org', ipv4='9.9.9.9')

    assert response.status_code == 404
    assert response.get_data(as_text=True).strip() == 'nohost'


def test_basic_auth_password_is_used_as_token(client, cloudflare_client):
    credentials = base64.b64encode(b'admin:' + TOKEN.encode()).decode()
    response = client.get('/', query_string={'zone': 'example.com',
                                             'record': 'www',
                                             'ipv4': '9.9.9.9'},
                          headers={'Authorization': 'Basic ' + credentials})

    assert response.get_data(as_text=True).strip() == 'good 9.9.9.9'


def test_missing_token_is_badauth(client, cloudflare_client):
    response = client.get('/', query_string={'zone': 'example.com',
                                             'ipv4': '9.9.9.9'})

    assert response.status_code == 401
    assert response.get_data(as_text=True).strip() == 'badauth'


def test_ipv6_prefix_and_suffix_are_combined(client, cloudflare_client):
    response = get(client, zone='example.com', record='www',
                   ipv6prefix='2001:db8:abc:def::/64', ipv6suffix='::dead:beef')

    assert response.status_code == 200
    _, payload = cloudflare_client.edits[0]
    assert payload['content'] == '2001:db8:abc:def::dead:beef'


def test_ipv6_prefix_without_suffix_is_rejected(client, cloudflare_client):
    response = get(client, zone='example.com', record='www',
                   ipv6prefix='2001:db8:abc:def::/64')

    assert response.status_code == 400
    assert response.get_data(as_text=True).strip() == 'badagent'


def test_unsubstituted_placeholders_are_ignored(client, cloudflare_client):
    response = get(client, zone='example.com', record='www', ipv4='9.9.9.9',
                   ipv6='<ip6addr>')

    assert response.status_code == 200
    assert [payload['type'] for _, payload in cloudflare_client.edits] == ['A']


def test_request_without_any_address_is_badagent(client, cloudflare_client):
    response = get(client, zone='example.com', record='www')

    assert response.status_code == 400
    assert response.get_data(as_text=True).strip() == 'badagent'


def test_myip_alias_carries_both_families(client, cloudflare_client):
    response = get(client, zone='example.com', record='www',
                   myip='9.9.9.9,2001:db8::99')

    assert response.status_code == 200
    assert [payload['content'] for _, payload in cloudflare_client.edits] == \
        ['9.9.9.9', '2001:db8::99']


def test_link_local_address_is_rejected(client, cloudflare_client):
    response = get(client, zone='example.com', record='www',
                   ipv6='fe80::1')

    assert response.status_code == 400
    assert response.get_data(as_text=True).strip() == 'badagent'


def test_missing_record_is_nohost(client):
    fake = FakeClient(records=[])
    with mock.patch.object(dyndns, 'Cloudflare', return_value=fake):
        response = get(client, zone='example.com', record='www',
                       ipv4='9.9.9.9')

    assert response.status_code == 404
    assert response.get_data(as_text=True).strip() == 'nohost'


def test_unknown_zone_is_nohost(client):
    fake = FakeClient(zones=[])
    with mock.patch.object(dyndns, 'Cloudflare', return_value=fake):
        response = get(client, zone='example.net', ipv4='9.9.9.9')

    assert response.status_code == 404


def test_json_format_is_available(client, cloudflare_client):
    response = get(client, zone='example.com', record='www', ipv4='9.9.9.9',
                   format='json')

    assert response.mimetype == 'application/json'
    assert response.get_json() == {'status': 'success', 'code': 'good',
                                   'message': 'Update successful.',
                                   'ip': '9.9.9.9'}


def test_dyndns2_update_path_is_served(client, cloudflare_client):
    response = client.get('/nic/update',
                          query_string={'token': TOKEN, 'zone': 'example.com',
                                        'record': 'www', 'ipv4': '9.9.9.9'})

    assert response.status_code == 200


def test_missing_aaaa_record_leaves_a_record_untouched(client):
    fake = FakeClient(records=[make_record('A', '1.2.3.4')])
    with mock.patch.object(dyndns, 'Cloudflare', return_value=fake):
        response = get(client, zone='example.com', record='www',
                       ipv4='9.9.9.9', ipv6='2001:db8::99')

    assert response.status_code == 404
    assert response.get_data(as_text=True).strip() == 'nohost'
    assert fake.edits == []
