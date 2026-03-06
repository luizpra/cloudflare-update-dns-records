# Cloudflare Auto DNS Updater (A record)

This Python script updates a Cloudflare DNS **A** record to your current public IPv4.

## Files

- `update_dns.py` - updater script (Python standard library only)
- `run.sh` - shell wrapper that loads `.env` before running the script
- `.env.example` - template for your environment variables

## 1) Cloudflare prerequisites

Create an API token in Cloudflare with:
- **Permissions**: `Zone.DNS:Edit`
- **Zone Resources**: only the specific zone you want to update

You also need:
- `Zone ID` (Cloudflare Dashboard -> your domain -> right sidebar)
- Target DNS name (for example: `home.example.com`)

## 2) Configure environment variables

**Option A – `.env` file (recommended)**

```bash
cp .env.example .env
# Edit .env and fill in your values
```

Then use `run.sh` (see step 3) to load it automatically.

**Option B – export manually**

```bash
export CF_API_TOKEN="your_token_here"
export CF_ZONE_ID="your_zone_id_here"
export CF_RECORD_NAME="home.example.com"
```

Optional variables:

```bash
export CF_TTL="1"               # 1 = automatic
export CF_PROXIED="false"       # true/false
export CF_CREATE_MISSING="true" # default true
```

## 3) Run manually

**Using the shell wrapper** (loads `.env` automatically):

```bash
./run.sh
```

Useful optional flags:

```bash
./run.sh --dns-only
./run.sh --proxied
./run.sh --no-create-missing
./run.sh --ip 203.0.113.10
```

You can also run the Python script directly (environment variables must be set):

```bash
python3 update_dns.py
```

## 4) Automate with cron

Run every 5 minutes:

```cron
*/5 * * * * cd /path/to/auto-dns && ./run.sh >> /tmp/auto-dns.log 2>&1
```

## Expected behavior

- If IP is unchanged: exits successfully with "No change needed"
- If IP changed: updates record and exits successfully
- If record is missing: creates record by default (`--no-create-missing` disables this)
- On errors: prints message to stderr and exits with code `1`
