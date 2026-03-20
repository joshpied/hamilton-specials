# Hamilton Weekly Grocery Specials

Automatically scrapes grocery flyers every Thursday, generates a static HTML site, and emails it to a recipient list.

**Cost: ~$0.10–0.20/week** (Claude Haiku API + web search × 9 stores). Email via Resend free tier.

---

## How it works

```
Every Thursday 8am ET
  → scraper.py runs on GitHub Actions
  → calls Claude Haiku API (web search) for each store
  → generates dist/index.html  (interactive static site)
  → generates dist/email.html  (email-safe table layout)
  → sends email via Resend API
  → deploys dist/ to GitHub Pages
```

---

## Setup (one-time, ~15 minutes)

### 1. Create the GitHub repo

```bash
git clone https://github.com/YOU/hamilton-specials.git
cd hamilton-specials
# copy these files in, then:
git add .
git commit -m "init"
git push
```

### 2. Enable GitHub Pages

- Repo → **Settings → Pages**
- Source: **Deploy from a branch**
- Branch: `gh-pages` / `/ (root)`
- Save

Your static site will be at `https://YOU.github.io/hamilton-specials/`

### 3. Get your API keys

**Anthropic (Claude)**
- https://console.anthropic.com → API Keys → Create key
- Fund your account — each weekly run costs ~$0.10–0.20

**Resend (email)**
- https://resend.com → sign up free
- Add & verify your sending domain (or use their test domain `onboarding@resend.dev` for testing)
- API Keys → Create API Key

### 4. Set GitHub Secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` |
| `RESEND_API_KEY` | `re_...` |
| `FROM_EMAIL` | `specials@yourdomain.com` |
| `TO_EMAILS` | `you@email.com,friend@email.com,family@email.com` |

`TO_EMAILS` is comma-separated — add as many as you like.

### 5. Test it manually

- Repo → **Actions → Weekly Grocery Specials → Run workflow**
- Watch the logs — each store should show `✓ N items`
- Check your inbox and `https://YOU.github.io/hamilton-specials/`

---

## Adding / removing stores

Edit `SOURCES` list in `scraper.py`. Each entry needs:

```python
{
    "id":           "storeid",        # lowercase, no spaces
    "name":         "Store Name",     # display name
    "color":        "#xxxxxx",        # text color for badge
    "bg":           "#xxxxxx",        # background color for badge
    "instructions": "Search for ...", # what to tell Claude
}
```

---

## Changing the schedule

Edit the cron line in `.github/workflows/weekly-specials.yml`:

```yaml
- cron: '0 13 * * 4'   # Thursday 13:00 UTC = 8am ET
```

Cron syntax: `minute hour day month weekday`
- Thursday = `4`, Friday = `5`, etc.
- Adjust the hour for your timezone offset from UTC.

---

## Files

```
.github/workflows/weekly-specials.yml   GitHub Actions workflow
scraper.py                              Main script
requirements.txt                        Python deps (just httpx)
dist/                                   Generated output (git-ignored)
  index.html                            Interactive static site
  email.html                            Email-safe version
  data.json                             Raw JSON data
```

---

## Troubleshooting

**A store returns 0 items**
Claude couldn't find parseable flyer data. Check the Actions log for that store. The flyer site may have changed — update `instructions` in `SOURCES`.

**Email not arriving**
- Check Resend dashboard for delivery status
- Verify your `FROM_EMAIL` domain is verified in Resend
- Check spam folder

**GitHub Pages not updating**
- Confirm `gh-pages` branch exists after first run
- Settings → Pages → confirm source is `gh-pages`
