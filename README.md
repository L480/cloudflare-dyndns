# cloudflare-dyndns

Middleware for updating [Cloudflare](https://www.cloudflare.com/) DNS records through an [AVM FRITZ!Box](https://en.avm.de/products/fritzbox/).

Built for **FRITZ!OS 8.40 and newer**: the service answers in the DynDNS2 dialect FRITZ!OS expects (`good` / `nochg` / `badauth` …), accepts the API token as the DynDNS password, understands the `<domain>` and `<ip6lanprefix>` placeholders, and talks to Cloudflare through the current [Cloudflare Python SDK](https://github.com/cloudflare/cloudflare-python) (v5, API v4).

## Getting started

### Create a Cloudflare API token

Create a [Cloudflare API token](https://dash.cloudflare.com/profile/api-tokens) with **read permissions** for the scope `Zone.Zone` and **edit permissions** for the scope `Zone.DNS`.

![Create a Cloudflare custom token](./images/create-cloudflare-token.png "Create a Cloudflare custom token")

The A and/or AAAA record you want to keep up to date has to exist in Cloudflare already — cloudflare-dyndns updates records, it does not create them. Set it to any address to begin with; TTL, proxy status and comment are preserved on every update.

### :rocket: Option 1: Self-host cloudflare-dyndns

#### Run on Docker

Start cloudflare-dyndns:

```bash
docker run -p 80:8080 ghcr.io/l480/cloudflare-dyndns:latest
```

The container listens on port **8080** and runs as an unprivileged user. Optionally pass the API token to the container instead of putting it into the update URL:

```bash
docker run -p 80:8080 -e CLOUDFLARE_API_TOKEN=<your-token> ghcr.io/l480/cloudflare-dyndns:latest
```

#### Run on Kubernetes

Use the [Helm Chart](./helm-chart) to deploy cloudflare-dyndns to Kubernetes or directly [pull it from the repositories OCI registry](https://helm.sh/docs/topics/registries/#enabling-oci-support):

```bash
helm pull oci://ghcr.io/l480/charts/cloudflare-dyndns --version 0.2.0
```

To keep the token out of the update URL, put it into a secret and reference it:

```bash
kubectl create secret generic cloudflare-dyndns --from-literal=token=<your-token>
helm upgrade --install cloudflare-dyndns oci://ghcr.io/l480/charts/cloudflare-dyndns \
  --set cloudflareApiToken.existingSecret=cloudflare-dyndns
```

Terminate TLS in front of the service (for example with an ingress and a Let's Encrypt certificate). A FRITZ!Box will not send updates to an endpoint whose certificate it cannot validate.

### :cloud: Option 2: Use my free cloud service

If you don't want to host cloudflare-dyndns yourself, feel free to use my cloud service. Just use this Update URL in your FRITZ!Box:

```
https://dyndns.nicoo.org/?token=<pass>&record=www&zone=example.com&ipv4=<ipaddr>&ipv6=<ip6addr>
```

### Configure your FRITZ!Box

In FRITZ!OS 8.40+ go to **Internet > Permit Access > DynDNS**, enable DynDNS and pick the provider **Custom**.

| FRITZ!Box Setting | Value                                                                                             | Description                                                                                                                             |
| ----------------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Update URL        | `https://dyndns.nicoo.org/?token=<pass>&record=www&zone=example.com&ipv4=<ipaddr>&ipv6=<ip6addr>` | Replace the URL parameter `record` and `zone` with your domain name. If required you can omit either the `ipv4` or `ipv6` URL parameter. |
| Domain Name       | www.example.com                                                                                   | The FQDN from the URL parameter `record` and `zone`.                                                                                    |
| Username          | admin                                                                                             | You can choose whatever value you want.                                                                                                 |
| Password          | ●●●●●●                                                                                            | The API token you’ve created earlier.                                                                                                   |

Instead of naming the zone and the record explicitly, you can let the FRITZ!Box fill in the domain name it is configured with:

```
https://dyndns.nicoo.org/?token=<pass>&domain=<domain>&ipv4=<ipaddr>&ipv6=<ip6addr>
```

cloudflare-dyndns then picks the matching zone from your Cloudflare account itself.

#### Updating a host behind the FRITZ!Box (IPv6)

A FRITZ!Box only knows its own IPv6 address, so `<ip6addr>` points at the box. To keep the AAAA record of a server *behind* the box current, hand over the delegated prefix and the interface identifier of that host:

```
https://dyndns.nicoo.org/?token=<pass>&record=nas&zone=example.com&ipv4=<ipaddr>&ipv6prefix=<ip6lanprefix>&ipv6suffix=::1234:5678:9abc:def0
```

The suffix is the part of the server's IPv6 address behind the prefix; it is combined with `<ip6lanprefix>` on every update. On the FRITZ!Box, `Home Network > Network > <device> > IPv6 Interface ID` shows it.

## URL parameters

| Parameter    | Required                     | Description                                                                                              |
| ------------ | ---------------------------- | -------------------------------------------------------------------------------------------------------- |
| `token`      | unless sent as the password  | Cloudflare API token. Alternatively sent as the HTTP basic auth password (`<pass>`), as a bearer token, or configured via `CLOUDFLARE_API_TOKEN`. |
| `zone`       | unless `domain` is used      | Your Cloudflare zone, e.g. `example.com`.                                                                |
| `record`     | no                           | Host part of the record, e.g. `www`. Omit it to update the zone apex.                                    |
| `domain`     | unless `zone` is used        | FQDN to update, e.g. `<domain>`. The zone is resolved automatically.                                     |
| `ipv4`       | one address is required      | New IPv4 address (`<ipaddr>`).                                                                           |
| `ipv6`       | one address is required      | New IPv6 address (`<ip6addr>`).                                                                          |
| `myip`       | no                           | DynDNS2 alias accepting a comma-separated IPv4/IPv6 pair.                                                |
| `ipv6prefix` | no                           | Delegated IPv6 prefix (`<ip6lanprefix>`). Requires `ipv6suffix` and takes precedence over `ipv6`.        |
| `ipv6suffix` | with `ipv6prefix`            | Interface identifier of the host behind the FRITZ!Box, e.g. `::1234:5678:9abc:def0`.                     |
| `format`     | no                           | Set to `json` for a JSON response instead of the DynDNS2 plain text one.                                 |

Placeholders that the FRITZ!Box could not substitute (`<ipaddr>`, `0.0.0.0`, `::`, empty values) are ignored instead of being written to DNS, so a box that has no IPv6 yet does not break the IPv4 update.

The endpoint is served at `/`, `/update` and `/nic/update`.

## Response codes

The default response is DynDNS2 plain text, which is what FRITZ!OS understands:

| Response   | HTTP    | Meaning                                                             |
| ---------- | ------- | --------------------------------------------------------------------- |
| `good <ip>`  | 200     | Record updated.                                                     |
| `nochg <ip>` | 200     | Record already pointed at that address.                             |
| `badauth`  | 401/403 | Token missing, rejected by Cloudflare, or lacking permissions.      |
| `badagent` | 400     | Missing or unusable address parameters.                             |
| `notfqdn`  | 400     | Neither `zone` nor a fully qualified `domain` was given.            |
| `nohost`   | 404     | Zone or A/AAAA record does not exist.                               |
| `abuse`    | 429     | Cloudflare rate limit reached.                                      |
| `911`      | 502     | Cloudflare API error — retry later.                                 |

Append `&format=json` (or send `Accept: application/json`) to get `{"status": …, "code": …, "message": …, "ip": …}` instead.

## Configuration

| Environment variable      | Default   | Description                                                     |
| ------------------------- | --------- | ----------------------------------------------------------------- |
| `CLOUDFLARE_API_TOKEN`    | –         | Fallback token if the request carries none.                     |
| `PORT`                    | `8080`    | Port to listen on.                                              |
| `HOST`                    | `0.0.0.0` | Address to bind to.                                             |
| `THREADS`                 | `4`       | Waitress worker threads.                                        |
| `LOG_LEVEL`               | `INFO`    | Python log level.                                               |
| `CLOUDFLARE_TIMEOUT`      | `10`      | Cloudflare API timeout in seconds.                              |
| `CLOUDFLARE_MAX_RETRIES`  | `2`       | Retries for failed Cloudflare API calls.                        |

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest tests
python app.py
```

## Upgrading from earlier versions

* Responses are DynDNS2 plain text by default; use `format=json` for the previous JSON body.
* The container listens on `8080` instead of `80` and runs as a non-root user (`docker run -p 80:8080 …`).
* Helm chart `0.2.0` maps the service port `80` to the new container port.
* Existing update URLs keep working — `token`, `zone`, `record`, `ipv4` and `ipv6` are unchanged.
