# Daily Digest Agent - Setup Instructions

**What this does:** Scrapes WSJ, Bloomberg, HBR, FT daily at 9pm EST, filters for supply chain/ops/sports analytics/financial markets content, and emails you the top 5 articles.

---

## Quick Setup (15 minutes)

### 1. Create GitHub Repository

```bash
# On your machine
cd ~/Desktop  # or wherever you want this
git clone <paste-the-repo-url-you-create>
cd daily-digest-agent

# Copy these files into the repo
# (I'll provide them in the next step)
```

**Create a new repo on GitHub:**
- Go to github.com/new
- Name it: `daily-digest-agent`
- Set to **Public** (required for free GitHub Actions)
- Don't initialize with README
- Click "Create repository"

### 2. Get SendGrid API Key (Free)

1. Go to https://signup.sendgrid.com/
2. Sign up (free tier = 100 emails/day, plenty)
3. Complete verification
4. Navigate to Settings > API Keys
5. Click "Create API Key"
   - Name: `daily-digest`
   - Permissions: **Full Access** (or at minimum "Mail Send")
6. **Copy the API key** (you only see this once)

7. **Verify sender email:**
   - Go to Settings > Sender Authentication
   - Click "Verify a Single Sender"
   - Use any email you control (can be joshjdi24@gmail.com)
   - Check that email and click verification link
   - This is the "from" address in your digests

### 3. Add Secret to GitHub

1. Go to your repo: `github.com/YOUR_USERNAME/daily-digest-agent`
2. Click **Settings** > **Secrets and variables** > **Actions**
3. Click "New repository secret"
   - Name: `SENDGRID_API_KEY`
   - Value: [paste the API key from step 2]
4. Click "Add secret"

### 4. Push Code to GitHub

```bash
# In your daily-digest-agent folder
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/daily-digest-agent.git
git push -u origin main
```

### 5. Test the Workflow

**Manual test first:**
1. Go to your repo on GitHub
2. Click **Actions** tab
3. Click "Daily Digest Scraper" on the left
4. Click "Run workflow" dropdown > "Run workflow"
5. Wait ~30 seconds
6. Check your email (joshjdi24@gmail.com)

**If it worked:** You'll get an email with articles within 1-2 minutes.

**If it failed:** 
- Click on the failed run
- Check logs for errors
- Common issues:
  - SendGrid API key not set correctly
  - Sender email not verified in SendGrid
  - RSS feeds changed URLs (fixable, just ping me)

---

## How It Works

### Scheduling
- Runs daily at **9:00 PM EST** (2:00 AM UTC)
- GitHub Actions triggers automatically
- No server/machine needed on your end

### Filtering Logic
```python
# Includes articles matching:
- Supply chain: logistics, inventory, trade policy, tariffs, manufacturing
- Sports analytics: NBA/NFL/PGA analytics, betting models, projections
- Financial: Fed policy, interest rates, macro, sector trends

# Excludes:
- Celebrity gossip, culture war politics, low-signal noise
```

### Scoring System
- Each matched keyword = +1 point
- Articles sorted by score (highest first)
- Top 5 sent to you
- Duplicate tracking prevents re-sending same article

### State Management
- `sent_articles.json` tracks what you've already received
- Auto-commits after each run
- Prevents duplicate sends across days

---

## Customization

### Change Timing
Edit `.github/workflows/daily-digest.yml`:
```yaml
# Line 5-6
- cron: '0 2 * * *'  # 2am UTC = 9pm EST

# For 7am EST (12pm UTC):
- cron: '0 12 * * *'
```

### Add Keywords
Edit `scraper.py` lines 15-35:
```python
INCLUDE_KEYWORDS = [
    'supply chain',
    # Add yours here
    'warehouse automation',
    'nfl analytics',
]
```

### Change Article Count
Edit `scraper.py` line 203:
```python
top_articles = new_articles[:5]  # Change 5 to whatever
```

### Add More Sources
Edit `scraper.py` lines 10-15:
```python
SOURCES = {
    'wsj': 'https://feeds.a.dj.com/rss/RSSWorldNews.xml',
    'your_source': 'https://example.com/rss',  # Add here
}
```

---

## Troubleshooting

### "No articles sent"
- RSS feeds might be down
- Filters too aggressive (no matches)
- Check GitHub Actions logs for details

### Email not arriving
- Check spam folder
- Verify sender email in SendGrid
- Confirm API key is set in GitHub secrets

### Want to see what it scraped?
Check GitHub Actions logs:
- Actions tab > Latest run > Click job
- Scroll to "Run scraper" step
- Shows: articles fetched, filtered count, what was sent

---

## Cost
- **GitHub Actions:** Free (2,000 minutes/month on public repos)
- **SendGrid:** Free (100 emails/day tier)
- **Total:** $0/month

---

## Files Structure
```
daily-digest-agent/
├── scraper.py                    # Main logic
├── requirements.txt              # Python dependencies
├── .github/workflows/
│   └── daily-digest.yml         # Scheduler config
├── sent_articles.json           # Auto-generated, tracks history
└── README.md                    # This file
```

---

## Next Steps After Setup

1. **Monitor for a week** — see if article quality matches expectations
2. **Tune keywords** — add domain-specific terms as you find them
3. **Adjust filters** — if too many/few articles, tweak scoring
4. **Optional:** Add a second daily send (morning briefing?) by duplicating workflow with different cron time

---

**Support:** If something breaks, check GitHub Actions logs first. 90% of issues show up there with clear error messages.
