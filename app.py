"""Middleware for updating Cloudflare DNS records from an AVM FRITZ!Box.

Speaks the DynDNS2 dialect that FRITZ!OS 8.40 and newer expect (plain text
``good``/``nochg``/``badauth`` responses) and talks to Cloudflare through the
official ``cloudflare`` Python SDK (v5, API v4).
"""

import ipaddress
import logging
import os

import cloudflare
import flask
import waitress
from cloudflare import Cloudflare

# DynDNS2 return codes. FRITZ!OS looks at the first word of the response body
# and reports "provider returned an error" for anything it does not know.
GOOD = 'good'
NOCHG = 'nochg'
BADAUTH = 'badauth'
BADAGENT = 'badagent'
NOTFQDN = 'notfqdn'
NOHOST = 'nohost'
ABUSE = 'abuse'
SERVERERROR = '911'

# Values a FRITZ!Box sends when it has no usable address yet, or when the
# update URL was pasted without the placeholders being substituted.
PLACEHOLDERS = {'', 'none', 'null', '0.0.0.0', '::',
                '<ipaddr>', '<ip6addr>', '<ip6lanprefix>'}

API_TIMEOUT = float(os.environ.get('CLOUDFLARE_TIMEOUT', '10'))
API_RETRIES = int(os.environ.get('CLOUDFLARE_MAX_RETRIES', '2'))

log = logging.getLogger('cloudflare-dyndns')


class DynDnsError(Exception):
    """An error that maps onto a DynDNS2 return code and an HTTP status."""

    def __init__(self, code, http_status, message):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message = message


def wants_json():
    """FRITZ!Box gets plain text, everything else can ask for JSON."""
    if flask.request.args.get('format', '').lower() == 'json':
        return True
    accept = flask.request.accept_mimetypes
    return accept['application/json'] > accept['text/plain']


def respond(code, http_status, message, ip=None):
    if wants_json():
        status = 'success' if code in (GOOD, NOCHG) else 'error'
        body = {'status': status, 'code': code, 'message': message}
        if ip:
            body['ip'] = ip
        return flask.jsonify(body), http_status

    text = '{} {}'.format(code, ip) if ip else code
    return flask.Response('{}\n'.format(text), status=http_status,
                          mimetype='text/plain')


def get_token():
    """Token from the URL, from HTTP basic/bearer auth, or from the environment.

    FRITZ!OS sends the DynDNS password both as ``<pass>`` in the update URL and
    as HTTP basic auth, so self-hosters can keep the token out of the URL.
    """
    token = flask.request.args.get('token')
    if token:
        return token.strip()

    auth = flask.request.authorization
    if auth is not None:
        if auth.type == 'basic' and auth.password:
            return auth.password.strip()
        if auth.type == 'bearer' and auth.token:
            return auth.token.strip()

    token = os.environ.get('CLOUDFLARE_API_TOKEN')
    if token:
        return token.strip()

    raise DynDnsError(BADAUTH, 401, 'Missing Cloudflare API token. Pass it as '
                                    'the token URL parameter or as the DynDNS '
                                    'password.')


def parse_ip(raw, version, source):
    """Validate one address the FRITZ!Box sent us."""
    if raw is None:
        return None

    raw = raw.strip()
    if raw.lower() in PLACEHOLDERS:
        log.info('Ignoring unusable %s value %r.', source, raw)
        return None

    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        raise DynDnsError(BADAGENT, 400,
                          'Invalid {} address: {}.'.format(source, raw))

    if address.version != version:
        raise DynDnsError(BADAGENT, 400,
                          '{} is not an IPv{} address.'.format(raw, version))

    if (address.is_unspecified or address.is_loopback or address.is_multicast
            or address.is_link_local):
        raise DynDnsError(BADAGENT, 400,
                          '{} is not a routable address.'.format(raw))

    if address.is_private:
        # DS-Lite and double NAT hand out addresses that are useless in public
        # DNS, but publishing them is the caller's decision.
        log.warning('Publishing non-public %s address.', source)

    return str(address)


def ipv6_from_prefix(prefix, suffix):
    """Combine the FRITZ!Box ``<ip6lanprefix>`` with a host's interface id.

    A FRITZ!Box only knows its own IPv6 address, so a server behind it has to
    be addressed as "prefix from the box" plus "suffix of that host".
    """
    try:
        network = ipaddress.IPv6Network(prefix.strip(), strict=False)
    except ValueError:
        raise DynDnsError(BADAGENT, 400,
                          'Invalid IPv6 prefix: {}.'.format(prefix))

    try:
        interface_id = ipaddress.IPv6Address(suffix.strip())
    except ValueError:
        raise DynDnsError(BADAGENT, 400,
                          'Invalid IPv6 suffix: {}.'.format(suffix))

    address = ipaddress.IPv6Address(
        int(network.network_address) | int(interface_id))

    if address not in network:
        raise DynDnsError(BADAGENT, 400,
                          'Suffix {} does not fit into prefix {}.'.format(
                              suffix, network.with_prefixlen))

    return str(address)


def collect_addresses():
    """Read ipv4/ipv6 (or the DynDNS2 ``myip`` alias) from the query string."""
    args = flask.request.args
    ipv4 = parse_ip(args.get('ipv4'), 4, 'IPv4')
    ipv6 = parse_ip(args.get('ipv6'), 6, 'IPv6')

    myip = args.get('myip')
    if myip:
        for candidate in myip.split(','):
            candidate = candidate.strip()
            if candidate.lower() in PLACEHOLDERS:
                continue
            try:
                version = ipaddress.ip_address(candidate).version
            except ValueError:
                raise DynDnsError(BADAGENT, 400,
                                  'Invalid myip address: {}.'.format(candidate))
            if version == 4 and ipv4 is None:
                ipv4 = parse_ip(candidate, 4, 'IPv4')
            elif version == 6 and ipv6 is None:
                ipv6 = parse_ip(candidate, 6, 'IPv6')

    prefix = args.get('ipv6prefix')
    suffix = args.get('ipv6suffix')
    if prefix and prefix.strip().lower() not in PLACEHOLDERS:
        if not suffix:
            raise DynDnsError(BADAGENT, 400, 'The ipv6prefix URL parameter '
                                             'requires an ipv6suffix.')
        ipv6 = ipv6_from_prefix(prefix, suffix)

    if ipv4 is None and ipv6 is None:
        raise DynDnsError(BADAGENT, 400, 'Missing ipv4, ipv6 or ipv6prefix URL '
                                         'parameter.')

    return ipv4, ipv6


def resolve_zone(client, domain):
    """Find the zone a fully qualified ``<domain>`` belongs to.

    Asks for the longest candidate first, so ``www.home.example.com`` lands in
    the ``home.example.com`` zone if that one is delegated separately.
    """
    labels = domain.split('.')
    for index in range(len(labels) - 1):
        candidate = '.'.join(labels[index:])
        zones = client.zones.list(name=candidate).result
        if zones:
            return zones[0]

    raise DynDnsError(NOHOST, 404,
                      'No zone in this account covers {}.'.format(domain))


def resolve_target(client):
    """Work out the zone and the FQDN to update.

    Either ``domain`` (the FRITZ!Box ``<domain>`` placeholder) or ``zone`` plus
    an optional ``record`` may be used.
    """
    args = flask.request.args
    domain = args.get('domain')
    zone_name = args.get('zone')
    record = args.get('record')

    if domain:
        domain = domain.strip().rstrip('.').lower()
        if '.' not in domain:
            raise DynDnsError(NOTFQDN, 400,
                              '{} is not a fully qualified domain name.'.format(
                                  domain))
        zone = resolve_zone(client, domain)
        return zone, domain

    if not zone_name:
        raise DynDnsError(NOTFQDN, 400,
                          'Missing zone or domain URL parameter.')

    zone_name = zone_name.strip().rstrip('.').lower()
    zones = client.zones.list(name=zone_name).result
    if not zones:
        raise DynDnsError(NOHOST, 404,
                          'Zone {} does not exist.'.format(zone_name))

    record = record.strip().rstrip('.').lower() if record else None
    fqdn = '{}.{}'.format(record, zone_name) if record else zone_name
    return zones[0], fqdn


def fetch_record(client, zone_id, fqdn, record_type):
    """Look up the existing A/AAAA record. This service never creates records."""
    records = client.dns.records.list(zone_id=zone_id, type=record_type,
                                      name={'exact': fqdn}, match='all').result

    if not records:
        raise DynDnsError(NOHOST, 404,
                          '{} record for {} does not exist.'.format(
                              record_type, fqdn))

    return records[0]


def write_record(client, zone_id, record, content):
    """Point ``record`` at ``content``. True if it changed."""
    if record.content == content:
        log.info('%s record for %s already points at %s.',
                 record.type, record.name, content)
        return False

    # PATCH the record so ttl, proxied and comment survive the update.
    payload = {'zone_id': zone_id, 'type': record.type, 'name': record.name,
               'content': content, 'ttl': record.ttl}
    if record.proxied is not None:
        payload['proxied'] = record.proxied

    client.dns.records.edit(record.id, **payload)
    log.info('Updated %s record for %s: %s -> %s.',
             record.type, record.name, record.content, content)
    return True


def handle_update():
    token = get_token()
    ipv4, ipv6 = collect_addresses()

    client = Cloudflare(api_token=token, timeout=API_TIMEOUT,
                        max_retries=API_RETRIES)
    zone, fqdn = resolve_target(client)

    wanted = []
    if ipv4 is not None:
        wanted.append(('A', ipv4))
    if ipv6 is not None:
        wanted.append(('AAAA', ipv6))

    # Look everything up first, so a missing AAAA record does not leave the A
    # record already rewritten.
    pending = [(fetch_record(client, zone.id, fqdn, record_type), content)
               for record_type, content in wanted]

    changed = False
    for record, content in pending:
        changed |= write_record(client, zone.id, record, content)

    reported_ip = ipv4 or ipv6
    if changed:
        return respond(GOOD, 200, 'Update successful.', reported_ip)
    return respond(NOCHG, 200, 'No update required.', reported_ip)


def create_app():
    app = flask.Flask(__name__)
    app.secret_key = os.urandom(24)

    @app.route('/', methods=['GET'])
    @app.route('/update', methods=['GET'])
    @app.route('/nic/update', methods=['GET'])
    def update():
        try:
            return handle_update()
        except DynDnsError as error:
            log.warning('Rejected update from %s: %s',
                        flask.request.remote_addr, error.message)
            return respond(error.code, error.http_status, error.message)
        except cloudflare.AuthenticationError:
            return respond(BADAUTH, 401, 'Cloudflare rejected the API token.')
        except cloudflare.PermissionDeniedError:
            return respond(BADAUTH, 403, 'The API token lacks Zone.Zone read '
                                         'or Zone.DNS edit permissions.')
        except cloudflare.NotFoundError:
            return respond(NOHOST, 404, 'Zone or record not found.')
        except cloudflare.RateLimitError:
            return respond(ABUSE, 429, 'Cloudflare rate limit reached.')
        except cloudflare.APIError as error:
            log.error('Cloudflare API error: %s', error)
            return respond(SERVERERROR, 502,
                           'Cloudflare API error: {}'.format(error))

    @app.route('/healthz', methods=['GET'])
    def healthz():
        return flask.jsonify({'status': 'success', 'message': 'OK'}), 200

    return app


app = create_app()


def main():
    logging.basicConfig(
        level=os.environ.get('LOG_LEVEL', 'INFO').upper(),
        format='%(asctime)s %(levelname)s %(name)s %(message)s')

    waitress.serve(app,
                   host=os.environ.get('HOST', '0.0.0.0'),
                   port=int(os.environ.get('PORT', '8080')),
                   threads=int(os.environ.get('THREADS', '4')),
                   url_scheme=os.environ.get('URL_SCHEME', 'http'))


if __name__ == '__main__':
    main()
