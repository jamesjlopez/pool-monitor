# Pentair API Discovery Notes

**Status:** INCOMPLETE — fill in after running Phase 1 MITM capture

## How to capture

```bash
# 1. Start discovery proxy
./monitor/sniffer_setup.sh discover

# 2. On iPhone: Settings > Wi-Fi > [your network] > Configure Proxy > Manual
#    Server: <this machine's IP>   Port: 8080

# 3. Visit http://mitm.it in Safari, install the certificate
#    Then: Settings > General > About > Certificate Trust Settings > enable mitmproxy cert

# 4. Open Pentair Home app:
#    - Navigate to pump status screen (triggers a status poll)
#    - Wait 60 seconds (catches background refresh)
#    - Change speed if safe
#    - Tap any other controls to capture control endpoints

# 5. Ctrl-C the proxy when done
# 6. Inspect: logs/discovery/telemetry_*.jsonl  (pre-filtered for pump keywords)
#             logs/discovery/session_*.jsonl     (all traffic)
```

## Network scan

Find the pump's IP on your LAN:

```bash
# Replace with your subnet
nmap -sV 192.168.1.0/24 --open -p 80,443,8080,8443
```

**Result:** TODO — fill in pump IP and any open ports found

## Findings

### Base URL

- [ ] Local (on LAN): `http://192.168.1.___`
- [ ] Cloud: `https://????.pentair.com`

### Auth method

TODO — from session logs, look for Authorization header, cookies, or x-api-key

```
# Example auth header found:
Authorization: Bearer <token>
```

### Status endpoint

**URL:** `TODO`
**Method:** `GET`
**Response example:**
```json
{
  "TODO": "fill in real response here"
}
```

**Field mapping:**
| Field | JSON key | Notes |
|-------|----------|-------|
| RPM   | `???`    |       |
| Watts | `???`    |       |
| GPH   | `???`    |       |
| Running | `???` |       |

### Control endpoint (for emergency shutoff)

**URL:** `TODO`
**Method:** `POST`
**Payload to turn off:**
```json
{"TODO": "fill in"}
```

## Next steps after discovery

1. Update `monitor/api_client.py`:
   - Set `PUMP_STATUS_ENDPOINT` and `PUMP_CONTROL_ENDPOINT`
   - Fill in `_build_headers()` with auth headers
   - Fill in `_parse_status()` with real field names
   - Set `self._base_url` to the correct base URL

2. Update `config.yaml`:
   - Set `pump.host` to the pump's IP (or leave blank if cloud-only)

3. Test the live client:
   ```bash
   python -m monitor.runner --once --dry-run
   ```
