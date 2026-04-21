# Problems & Solutions — Course RAG Deployment

A log of issues encountered during deployment to Oracle Cloud and how each was resolved.

---

## 1. Git Clone Failed — Password Authentication Not Supported

**Problem:**
```
remote: Invalid username or token. Password authentication is not supported for Git operations.
fatal: Authentication failed
```
GitHub no longer accepts account passwords for git operations over HTTPS.

**Fix:**
Generate a Personal Access Token (PAT) on GitHub:
- GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
- Select `repo` scope, generate token, copy it

Use the token in the clone URL:
```bash
git clone https://USERNAME:YOUR_TOKEN@github.com/USERNAME/REPO.git .
```

Store credentials so future pulls don't need the token again:
```bash
git config credential.helper store
```

---

## 2. .env File Missing on Server

**Problem:**
```
env file /opt/courserag/.env not found: stat /opt/courserag/.env: no such file or directory
```
The `.env` file is gitignored and was not included in the repository, so it didn't come down with `git clone`.

**Fix:**
Copy it from local machine to the server using `scp`:
```bash
scp -i C:\Users\tirth\.ssh\id_rsa_oracle C:\Users\tirth\OneDrive\Desktop\Agentic_Systems\Course_RAG\.env ubuntu@146.235.213.203:/opt/courserag/.env
```

---

## 3. Google OAuth Credentials Not Found Inside Docker Container

**Problem:**
```
Re-embedding failed: Google OAuth credentials not found at: /app/credentials/oauth_credentials.json
```
The `credentials/` folder files (`oauth_credentials.json` and `token.pickle`) exist on the VM but are not automatically copied into the running Docker container.

**Fix:**
First copy the files to the VM using `scp` from local machine:
```bash
scp -i C:\Users\tirth\.ssh\id_rsa_oracle credentials\oauth_credentials.json ubuntu@146.235.213.203:/opt/courserag/credentials/oauth_credentials.json

scp -i C:\Users\tirth\.ssh\id_rsa_oracle credentials\token.pickle ubuntu@146.235.213.203:/opt/courserag/credentials/token.pickle
```

Then copy them into the running container:
```bash
docker cp /opt/courserag/credentials/oauth_credentials.json courserag:/app/credentials/oauth_credentials.json
docker cp /opt/courserag/credentials/token.pickle courserag:/app/credentials/token.pickle
```

---

## 4. Re-embedding Crashed Server — Vision Fallback Hanging on Image PDFs

**Problem:**
Re-embedding a scanned image-based PDF (`Dixit_Skeath_Chapters_3_and_9.pdf`) caused the server to become unresponsive. The vision fallback was triggered on every page of the scanned textbook, each call timing out after several minutes, eventually crashing the VM.

**Root Cause:**
- `pdf_processor.py` uses a vision fallback (OpenAI GPT-4o-mini) for pages with fewer than 30 characters of extractable text
- Scanned PDFs have zero extractable text on every page, triggering vision on all pages simultaneously
- No timeout was set on the vision API calls
- 5 concurrent vision requests caused rate limiting and cascading timeouts

**Fix (`backend/services/pdf_processor.py`):**
- Added a **25-second timeout** per vision API call using `asyncio.wait_for`
- Reduced concurrency from 5 → **2 simultaneous** vision calls
- Added early bail-out: after **5 consecutive failures**, vision is disabled for the rest of that file

```python
vision_text = await asyncio.wait_for(
    self._vision_transcribe(client, model, png_b64),
    timeout=25,
)
```

---

## 5. DuckDNS Domain Disappeared

**Problem:**
The original DuckDNS domain (`jeremy-sucks.duckdns.org`) was gone from the account and already taken by someone else.

**Cause:**
DuckDNS automatically deletes domains that have not been updated in 45 days.

**Fix:**
- Created a new domain: `tirth-courserag.duckdns.org` pointing to `146.235.213.203`
- Updated `Caddyfile` locally and pushed to GitHub
- On the server, pulled the update and reloaded Caddy:
```bash
git pull origin master
sudo cp Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

**Prevention:**
Set up a cron job on the VM to ping DuckDNS regularly so the domain stays active:
```bash
echo "*/30 * * * * curl -s 'https://www.duckdns.org/update?domains=tirth-courserag&token=YOUR_TOKEN&ip=' > /dev/null" | crontab -
```

---

## 6. Website Unreachable — iptables REJECT Rule Blocking Ports 80/443

**Problem:**
```
connect to 146.235.213.203 port 80 failed: No route to host
```
The site was unreachable even after adding ports 80 and 443 to Oracle's Security List.

**Root Cause:**
The iptables chain had a `REJECT all` rule at position 5. The new ACCEPT rules for ports 80 and 443 were inserted at positions 6-9 — **after** the REJECT rule. iptables processes rules in order, so all traffic was rejected before the ACCEPT rules were ever reached.

```
5    REJECT     all  --  0.0.0.0/0   0.0.0.0/0   reject-with icmp-host-prohibited
6    ACCEPT     tcp  --  0.0.0.0/0   0.0.0.0/0   tcp dpt:443   ← never reached
7    ACCEPT     tcp  --  0.0.0.0/0   0.0.0.0/0   tcp dpt:80    ← never reached
```

**Fix:**
Insert the ACCEPT rules at position 5 (before the REJECT rule):
```bash
sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

This pushes the REJECT rule down to position 7, allowing HTTP/HTTPS traffic through first.
