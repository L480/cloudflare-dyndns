# Clients

## AVM FRITZ!Box

| FRITZ!Box Setting | Value | Description |
|---|---|---|
| Update URL | `https://dyndns.nicoo.org/?token=<pass>&record=www&zone=example.com&ipv4=<ipaddr>&ipv6=<ip6addr>` | Replace `record` and `zone` with your domain. Omit `ipv4` or `ipv6` if not needed. |
| Domain Name | `www.example.com` | The FQDN from `record` + `zone`. |
| Username | `admin` | Any value; unused by this service. |
| Password | your Cloudflare API token | The token created per the README. |

### Publishing LAN hosts too (`<ip6lanprefix>`)

The FRITZ!Box only knows its own addresses, but it also knows the IPv6
prefix it hands out to the LAN. If a host behind the box has a stable
interface ID (the last 64 bits of its address: EUI-64 derived from the MAC,
a fixed token, or a static DHCPv6 lease), one Update URL can publish the
box **and** the host:

```
https://dyndns.nicoo.org/?token=<pass>&zone=example.com&record=fritz,host&ipv4=<ipaddr>&ipv6=<ip6addr>&ipv6prefix=<ip6lanprefix>&ipv6suffix=host:9e6b:ff:fe50:179a
```

- `fritz.example.com` gets `A` = `<ipaddr>` and `AAAA` = `<ip6addr>`.
- `host.example.com` gets `A` = `<ipaddr>` (port-forward through the box)
  and `AAAA` = `<ip6lanprefix>` combined with `9e6b:ff:fe50:179a`.

Find the interface ID in the host's own address (everything after the
first four groups), or in the FRITZ!Box under *Home Network → Network →
device details*. Add more hosts with more `ipv6suffix` entries
(`&ipv6suffix=nas:1:2:3:4` or `&ipv6suffix=host:...,nas:...`); every host
named there must also be listed in `record`. Full semantics:
[`docs/api.md`](./api.md#per-record-ipv6-interface-ids-ipv6prefix--ipv6suffix).

### Troubleshooting (issue #36: "FRITZ!Box not updating")

1. **Check that the router actually calls the service.** Every request is
   now logged (structured JSON, one line per request, never containing the
   token). If self-hosting, `docker logs <container>` and look for a
   `dyndns update processed` line around the time of the WAN IP change. No
   log line at all means the router never fired the Update URL — the
   problem is in the FRITZ!Box configuration or its network path, not this
   service.
2. **Check the "Domain Name" field actually resolves.** Some FRITZ!OS
   versions validate that the configured Domain Name is a real, resolvable
   hostname before considering the DynDNS config valid.
3. **Proxied ("orange cloud") records confuse the router's own IP check.**
   If the `A`/`AAAA` record is proxied through Cloudflare, the FRITZ!Box's
   own "is my DynDNS hostname reachable" self-check will see Cloudflare's
   proxy IP, not the FRITZ!Box's WAN IP — this looks like a failure to the
   router even though the DNS update itself succeeded. Prefer an
   unproxied (DNS-only, "grey cloud") record for the DynDNS hostname if
   you see this.

## ddclient

```conf
protocol=dyndns2
use=web, web=checkip.amazonaws.com
server=dyndns.example.com
login=admin
password='<your-cloudflare-token>'
www.example.com
```

## inadyn

```conf
provider default@dyndns.org {
    hostname     = "www.example.com"
    username     = "admin"
    password     = "<your-cloudflare-token>"
    ddns-server  = "dyndns.example.com"
    ddns-path    = "/nic/update?hostname=%h&myip=%i"
}
```

## curl (manual test / cron)

```bash
curl -fsS "https://dyndns.example.com/?token=<token>&zone=example.com&record=www&ipv4=$(curl -fsS https://api.ipify.org)"
```

Or the dyndns2 endpoint:

```bash
curl -fsS -u "admin:<token>" \
  "https://dyndns.example.com/nic/update?hostname=www.example.com&myip=$(curl -fsS https://api.ipify.org)"
```

A cron one-liner (every 15 minutes):

```cron
*/15 * * * * curl -fsS "https://dyndns.example.com/?token=<token>&zone=example.com&record=www&ipv4=$(curl -fsS https://api.ipify.org)" >/dev/null
```
