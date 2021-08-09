# cloudflare-dyndns

Middleware for updating [Cloudflare](https://www.cloudflare.com/) DNS records through an [AVM FRITZ!Box](https://en.avm.de/products/fritzbox/).

## Getting started

### Create a Cloudflare API token

Create a [Cloudflare API token](https://dash.cloudflare.com/profile/api-tokens) with **read permissions** for the scope `Zone.Zone` and **edit permissions** for the scope `Zone.DNS` permissions.

![Create a Cloudflare custom token](./images/create-cloudflare-token.png "Create a Cloudflare custom token")

### Option 1: Self-host cloudflare-dyndns with Docker

Start cloudflare-dyndns:

```bash
docker run -p 80:80 ghcr.io/l480/cloudflare-dyndns:latest
```

### Option 2: Use my cloud service

If you don't want to host cloudflare-dyndns yourself, feel free to use my cloud service. Just enter `https://nicoo.org/cloudflare?token=<pass>&record=www&zone=your-domain.com&ipv4=<ipaddr>&ipv6=<ip6addr>` as Update URL in your FRITZ!Box.

### Configure your FRITZ!Box

| FRITZ!Box Setting | Value                                                                                                | Description                                                                                                                          |
| ----------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Update URL        | `https://your-domain.com/?token=<pass>&record=www&zone=your-domain.com&ipv4=<ipaddr>&ipv6=<ip6addr>` | Replace the URL parameter `record` and `zone` with your domain name. If required you can omit either the ipv4 or ipv6 URL parameter. |
| Domain Name       | www.your-domain.com                                                                                  | The FQDN from the URL parameter `record` and `zone`.                                                                                 |
| Username          | admin                                                                                                | You can choose whatever value you want.                                                                                              |
| Password          | 9NAFwkM7D3hBdM2acJWXDvdCzySqz4xf3MfBaP2b                                                             | The API token you’ve created earlier.                                                                                                |
