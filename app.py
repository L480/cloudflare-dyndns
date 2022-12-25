import os
import CloudFlare
import waitress
import flask

app = flask.Flask(__name__)


@app.route('/', methods=['GET'])
def main():
    token = flask.request.args.get('token')
    zone = flask.request.args.get('zone')
    record = flask.request.args.get('record')
    records = flask.request.args.get('records')
    ipv4 = flask.request.args.get('ipv4')
    ipv6 = flask.request.args.get('ipv6')
    cf = CloudFlare.CloudFlare(token=token)

    if not token:
        return flask.jsonify({'status': 'error', 'message': 'Missing token URL parameter.'}), 400
    if not zone:
        return flask.jsonify({'status': 'error', 'message': 'Missing zone URL parameter.'}), 400
    if not record and not records:
        return flask.jsonify({'status': 'error', 'message': 'Missing record or records URL parameter.'}), 400
    if not ipv4 and not ipv6:
        return flask.jsonify({'status': 'error', 'message': 'Missing ipv4 or ipv6 URL parameter.'}), 400

    try:
        zones = cf.zones.get(params={'name': zone})

        if not zones:
            return flask.jsonify({'status': 'error', 'message': 'Zone {} does not exist.'.format(zone)}), 404

        # put
        if record:
            put_dns_record(cf, zones, record, zone, ipv4, ipv6)
        for r in records:
            put_dns_record(cf, zones, r, zone, ipv4, ipv6)
    except CloudFlare.exceptions.CloudFlareAPIError as e:
        return flask.jsonify({'status': 'error', 'message': str(e)}), 500

    return flask.jsonify({'status': 'success', 'message': 'Update successful.'}), 200


@app.route('/healthz', methods=['GET'])
def healthz():
    return flask.jsonify({'status': 'success', 'message': 'OK'}), 200


def put_dns_record(cf, zones, record, zone, ipv4, ipv6):
    a_record = cf.zones.dns_records.get(zones[0]['id'], params={
        'name': '{}.{}'.format(record, zone), 'match': 'all', 'type': 'A'})
    aaaa_record = cf.zones.dns_records.get(zones[0]['id'], params={
        'name': '{}.{}'.format(record, zone), 'match': 'all', 'type': 'AAAA'})

    if ipv4 is not None and not a_record:
        return flask.jsonify(
            {'status': 'error', 'message': 'A record for {}.{} does not exist.'.format(record, zone)}), 404

    if ipv6 is not None and not aaaa_record:
        return flask.jsonify(
            {'status': 'error', 'message': 'AAAA record for {}.{} does not exist.'.format(record, zone)}), 404

    if ipv4 is not None and a_record[0]['content'] != ipv4:
        cf.zones.dns_records.put(zones[0]['id'], a_record[0]['id'], data={
            'name': a_record[0]['name'], 'type': 'A', 'content': ipv4, 'proxied': a_record[0]['proxied'],
            'ttl': a_record[0]['ttl']})

    if ipv6 is not None and aaaa_record[0]['content'] != ipv6:
        cf.zones.dns_records.put(zones[0]['id'], aaaa_record[0]['id'], data={
            'name': aaaa_record[0]['name'], 'type': 'AAAA', 'content': ipv6, 'proxied': aaaa_record[0]['proxied'],
            'ttl': aaaa_record[0]['ttl']})


app.secret_key = os.urandom(24)
waitress.serve(app, host='0.0.0.0', port=80)
