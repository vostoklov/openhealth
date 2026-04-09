# Sanitization Checklist

Detection patterns, before/after transforms, and the never-port list for the `openhealth-upstream` skill. Load this file only when you are actually running Phase 2 or Phase 4 of the main workflow.

Every pattern below is the **minimum** bar. If a contributor has unusual personal markers (a nickname, a pet's name used as a variable, a team-internal project codename), add them to the local scan before running.

---

## 1. Credentials

**Severity:** Critical. A single leaked token ends the contributor's OAuth session and can expose every record they ever synced.

### Detection patterns

```bash
# Env-style keys
grep -nE '(_TOKEN|_SECRET|_API_KEY|_PASSWORD|_PRIVATE_KEY)[[:space:]]*=' <file>

# Inline literals
grep -nE '(access_token|refresh_token|client_secret|client_id|bearer)[[:space:]]*[:=][[:space:]]*["'\'']' <file>

# HTTP auth headers
grep -nE 'Authorization[[:space:]]*:[[:space:]]*["'\'']?Bearer ' <file>

# Vercel / CI tokens
grep -nE '(VERCEL_OIDC_TOKEN|VERCEL_TOKEN|GITHUB_TOKEN|GH_TOKEN)' <file>

# Common secret prefixes
grep -nE '(sk_live_|sk_test_|ghp_|gho_|github_pat_|xoxb-|xoxp-|AKIA[0-9A-Z]{16})' <file>

# Long hex blobs (likely keys)
grep -nE '[a-f0-9]{32,}' <file>
```

### Classification

- Any match → **NEVER-PORT** for that specific line
- The surrounding function may still be **NEEDS-SANITIZATION** if the logic around the secret is reusable

### Transform

Replace the literal with an env var lookup that the contributor never had to touch:

Before (hypothetical personal code):
```python
WHOOP_CLIENT_SECRET = "a1b2c3…real secret…"
headers = {"Authorization": "Bearer " + access_token}
```

After (OpenHealth shape):
```python
import os

def load_credentials() -> WhoopCredentials:
    client_secret = os.getenv("OPENHEALTH_WHOOP_CLIENT_SECRET")
    if not client_secret:
        raise WhoopApiError("Missing OPENHEALTH_WHOOP_CLIENT_SECRET")
    return WhoopCredentials(client_secret=client_secret, ...)
```

Also make sure `.env.example` (which is already in the OpenHealth repo) documents the new variable.

---

## 2. Personal Identifiers (PII)

**Severity:** Critical. Real names, emails, phone numbers, and user IDs are non-recoverable once pushed.

### Detection patterns

```bash
# Emails (broad)
grep -inE '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}' <file>

# Phone numbers (very loose — review every hit)
grep -nE '\+?[0-9][0-9 ()\-]{7,}[0-9]' <file>

# Telegram handles
grep -nE '@[A-Za-z][A-Za-z0-9_]{4,}' <file>

# Likely real-name identifiers anywhere in the code
# (the contributor must provide their own name list; below is a starter pattern)
grep -inE '(first_name|last_name|full_name|display_name)[[:space:]]*[:=]' <file>

# Literal user IDs (numeric)
grep -nE '(user_id|account_id|profile_id)[[:space:]]*[:=][[:space:]]*[0-9]+' <file>
```

### Classification

- Any real name, email, phone, or Telegram handle in code/comments/docstrings → **NEEDS-SANITIZATION**
- JSON/CSV files that *contain* these values → **NEVER-PORT**

### Transform

- Replace `owner="<real name>"` → `owner="user"`
- Replace `"author": "<real name>"` → `"author": "user"`
- Replace `user_id=15471089` → parameterize or drop entirely if not needed for logic
- Strip comments that name people: `# Ilya's WHOOP account` → delete the comment
- Strip docstring examples that quote real data: replace with synthetic example

Before:
```python
def sync_whoop(owner="alice", user_id=15471089):
    """Sync WHOOP for alice (alice@example.com)."""
```

After:
```python
def sync_whoop(owner: str = "user", *, user_id: int | None = None) -> SyncResult:
    """Sync WHOOP data for the configured owner."""
```

---

## 3. Real Health Data

**Severity:** Critical. Real heart-rate arrays, sleep sessions, rsid variants, and microbiota tables are the most sensitive content in any personal health repo.

### Detection patterns

```bash
# Any path under data/ is suspicious
find <personal-repo>/data -type f 2>/dev/null

# JSON files that look like API responses
grep -lE '("heart_rate"|"hrv"|"sleep_performance_percentage"|"recovery_score")' <personal-repo>

# Genetic data
find <personal-repo> -name '*.vcf' -o -name '*.fastq' -o -name '*rsid*' -o -name '*23andme*' 2>/dev/null

# Microbiota / lab exports
find <personal-repo> -name '*microbiota*' -o -name '*gutbio*' -o -name '*labcorp*' -o -name '*quest*' 2>/dev/null
```

### Classification

- **Every single file** under `data/raw/`, `data/processed/`, `data/index/`, or any directory holding sync outputs → **NEVER-PORT**. No exceptions.
- Parser/ingest logic that *operates on* those files → **SAFE** or **NEEDS-SANITIZATION**, but the test fixtures must be regenerated synthetically.

### Transform

Never copy real data. Generate synthetic fixtures inline in the test file:

Before (personal test reading real data):
```python
def test_whoop_parser():
    raw = Path("data/raw/whoop/2024-05-01.json").read_text()
    records = parse_whoop(raw)
    assert len(records) == 14
```

After (OpenHealth-shaped test with synthetic data):
```python
import json

def test_whoop_parser():
    synthetic = json.dumps({
        "cycle": [{"id": 1, "score": {"recovery_score": 72}, "start": "2024-05-01T00:00:00Z"}],
        "sleep": [{"id": 2, "score": {"sleep_performance_percentage": 88}}],
    })
    records = parse_whoop(synthetic)
    assert len(records) == 2
```

---

## 4. Personal File Paths

**Severity:** High. Leaked home paths reveal the contributor's real username, folder layout, and sometimes employer.

### Detection patterns

```bash
# macOS / Linux home paths
grep -nE '/Users/[^/[:space:]"'\'']+' <file>
grep -nE '/home/[^/[:space:]"'\'']+' <file>

# Tilde-expanded personal repos
grep -nE '~/(health-os|quantified-self|my-health|qs|self-labs)' <file>

# iCloud / Dropbox paths
grep -nE '(iCloud Drive|CloudDocs|Dropbox|Google Drive)' <file>
```

### Classification

- Any hardcoded personal path → **NEEDS-SANITIZATION**
- `.DS_Store`, `.vscode/`, IDE state files → **NEVER-PORT**

### Transform

Replace with parameters or repo-relative resolution:

Before:
```python
DATA_DIR = Path("/Users/alice/health-os/data")
```

After:
```python
def resolve_data_dir(repo_root: Path) -> Path:
    return repo_root / "data"
```

All OpenHealth code should use `openhealth.storage.ensure_repo_structure(repo_root)` and the `RepoPaths` dataclass from `openhealth.config` instead of hardcoding paths.

---

## 5. Hardcoded Locations

**Severity:** Medium. Home city and GPS coordinates pin the contributor to a physical location.

### Detection patterns

```bash
# GPS coordinates (loose)
grep -nE '[-+]?[0-9]{1,3}\.[0-9]{3,}[[:space:]]*,[[:space:]]*[-+]?[0-9]{1,3}\.[0-9]{3,}' <file>

# Likely city names anywhere in config (contributor should add their own list)
grep -inE '(home_city|default_location|timezone)[[:space:]]*[:=]' <file>
```

### Classification

- Any hardcoded city, address, or GPS → **NEEDS-SANITIZATION**

### Transform

Pass location as a parameter, default to `None`, and document that callers must provide their own:

Before:
```python
result = enrich_weather(date, location="Budapest")
```

After:
```python
def enrich_weather(date: str, location: str | None) -> WeatherSnapshot | None:
    if not location:
        return None
    ...
```

---

## 6. Binary and Data Files

**Severity:** Critical when they contain real data; otherwise low.

### Detection patterns

```bash
find <personal-repo> \
  \( -name '*.sqlite' -o -name '*.sqlite3' -o -name '*.db' \
     -o -name '*.vcf' -o -name '*.fastq' -o -name '*.parquet' \
     -o -name '*.pkl' -o -name '*.joblib' \) 2>/dev/null
```

### Classification

- All of the above → **NEVER-PORT**. The OpenHealth repo contains zero data files by design.

### Transform

None. These files are regenerated from scratch on a clean machine via `openhealth init`.

---

## The Never-Port List

These paths and file types must **never** appear in an OpenHealth PR, regardless of content:

- `data/raw/**`
- `data/processed/**`
- `data/index/**` (including `*.sqlite3`)
- `.env`, `.env.local`, `.env.production`, any file containing real env values
- Any `*.json` file that looks like a token cache (`*tokens*.json`, `*credentials*.json`)
- Any `*.vcf`, `*.fastq`, `*rsid*`, `*23andme*`, `*ancestry*`
- Any `*microbiota*`, `*labcorp*`, `*quest*`, lab result exports
- `.DS_Store`, `.vscode/`, `.idea/`, editor state
- Any file the contributor cannot confidently say "this contains zero real data" about

If any of these show up in the candidate set, **pause the workflow** and make the contributor explicitly acknowledge the exclusion before Phase 4 begins.

---

## Final Leak Grep (Phase 5)

After staging, every one of these should return **zero** lines. If any returns a match, stop and go back to Phase 4.

```bash
git diff --staged | grep -iE '(ilya|gindin)'                              # user's own name
git diff --staged | grep -iE '(access_token|refresh_token|client_secret)' # token literals
git diff --staged | grep -iE 'bearer [a-z0-9_.\-]+'                       # auth headers
git diff --staged | grep -E '/Users/[^/]+/'                               # home paths
git diff --staged | grep -E 'HEALTH_OS_'                                  # old env prefix
git diff --staged | grep -iE '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}'      # emails
git diff --staged | grep -nE '[a-f0-9]{32,}'                              # long hex blobs
```

Add the contributor's own name(s) and any project-internal codenames to the first grep before running.
