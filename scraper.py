import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import json

# Configuration
SOURCES = {
    'wsj': 'https://feeds.a.dj.com/rss/RSSWorldNews.xml',
    'bloomberg': 'https://www.bloomberg.com/feed/podcast/business.xml',
    'ft': 'https://www.ft.com/?format=rss',
    'hbr': 'https://feeds.hbr.org/harvardbusiness'
}

# Keywords for filtering (your 3 domains)
INCLUDE_KEYWORDS = [
    # Supply chain/ops
    'supply chain', 'logistics', 'inventory', 'trade policy', 'tariff', 
    'manufacturing', 'warehouse', 'distribution', 'retail operations',
    'procurement', 'vendor', 'freight', 'shipping', 'operations',
    
    # Sports analytics
    'sports analytics', 'betting', 'fantasy', 'nba', 'nfl', 'pga',
    'player tracking', 'expected goals', 'win probability', 'analytics model',
    'sports betting', 'projection system', 'vegas', 'moneyline',
    
    # Financial markets/macro
    'federal reserve', 'fed policy', 'interest rate', 'inflation',
    'macro', 'sector', 'portfolio', 'capital markets', 'treasury',
    'earnings', 'valuation', 'market structure', 'fiscal policy'
]

# Exclude categories
EXCLUDE_KEYWORDS = [
    'celebrity', 'kardashian', 'hollywood', 'royal family',
    'culture war', 'transgender bathroom', 'woke', 'cancel culture',
    'trump twitter', 'election rally', 'political scandal'
]

def fetch_rss_articles(url, source_name):
    """Fetch and parse RSS feed"""
    try:
        feed = feedparser.parse(url)
        articles = []
        
        for entry in feed.entries[:20]:  # Limit to recent 20 items
            article = {
                'title': entry.get('title', ''),
                'link': entry.get('link', ''),
                'summary': entry.get('summary', ''),
                'published': entry.get('published', ''),
                'source': source_name.upper()
            }
            articles.append(article)
        
        return articles
    except Exception as e:
        print(f"Error fetching {source_name}: {e}")
        return []

def score_article(article):
    """Score article based on keyword matching"""
    text = (article['title'] + ' ' + article['summary']).lower()
    
    # Check exclusions first
    for keyword in EXCLUDE_KEYWORDS:
        if keyword.lower() in text:
            return -1  # Exclude this article
    
    # Score based on inclusion keywords
    score = 0
    matched_keywords = []
    
    for keyword in INCLUDE_KEYWORDS:
        if keyword.lower() in text:
            score += 1
            matched_keywords.append(keyword)
    
    article['score'] = score
    article['matched_keywords'] = matched_keywords
    return score

def generate_why_read(article):
    """Generate contextual 'why read' based on matched keywords"""
    keywords = article.get('matched_keywords', [])
    
    if not keywords:
        return "Relevant to your focus areas"
    
    # Map keywords to contextual explanations
    contexts = {
        'supply chain': "Impacts logistics/inventory planning",
        'logistics': "Operational efficiency insights",
        'trade policy': "Affects global SC strategy",
        'inventory': "Relevant to ops optimization",
        'sports analytics': "New analytical methodology",
        'betting': "Model refinement opportunity",
        'nba': "Fantasy/analytics application",
        'federal reserve': "Macro environment shift",
        'interest rate': "Portfolio positioning relevant",
        'inflation': "Cost structure implications"
    }
    
    # Find first matching context
    for kw in keywords:
        kw_lower = kw.lower()
        for key, context in contexts.items():
            if key in kw_lower:
                return context
    
    return f"Matches: {', '.join(keywords[:2])}"

def format_email_html(articles):
    """Generate HTML email content"""
    date_str = datetime.now().strftime("%B %d, %Y")
    
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ border-bottom: 2px solid #000; padding-bottom: 10px; margin-bottom: 30px; }}
            .article {{ margin-bottom: 30px; padding-bottom: 20px; border-bottom: 1px solid #eee; }}
            .title {{ font-size: 18px; font-weight: 600; margin-bottom: 8px; color: #000; }}
            .meta {{ font-size: 13px; color: #666; margin-bottom: 8px; }}
            .why-read {{ font-size: 14px; color: #333; margin-bottom: 12px; font-style: italic; }}
            .link {{ display: inline-block; padding: 8px 16px; background: #000; color: #fff; text-decoration: none; border-radius: 4px; font-size: 14px; }}
            .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; font-size: 12px; color: #999; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>Daily Digest — {date_str}</h2>
            <p style="margin: 0; color: #666;">{len(articles)} articles curated for you</p>
        </div>
    """
    
    for i, article in enumerate(articles, 1):
        why_read = generate_why_read(article)
        
        html += f"""
        <div class="article">
            <div class="title">{i}. {article['title']}</div>
            <div class="meta">{article['source']} | {article.get('published', 'Recent')}</div>
            <div class="why-read">Why read: {why_read}</div>
            <a href="{article['link']}" class="link">Read article →</a>
        </div>
        """
    
    html += """
        <div class="footer">
            <p>Automated digest | Filtered for supply chain/ops, sports analytics, financial markets</p>
        </div>
    </body>
    </html>
    """
    
    return html

def send_email(articles, recipient_email):
    """Send digest via SendGrid"""
    api_key = os.environ.get('SENDGRID_API_KEY')
    
    if not api_key:
        print("ERROR: SENDGRID_API_KEY not set")
        return False
    
    html_content = format_email_html(articles)
    date_str = datetime.now().strftime("%B %d, %Y")
    
    message = Mail(
        from_email='noreply@yourdailynews.org',  # SendGrid will override with verified sender
        to_emails=recipient_email,
        subject=f'Daily Digest — {date_str} — {len(articles)} articles',
        html_content=html_content
    )
    
    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        print(f"Email sent! Status code: {response.status_code}")
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def load_sent_articles():
    """Load previously sent articles to avoid duplicates"""
    try:
        with open('sent_articles.json', 'r') as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()

def save_sent_articles(article_links):
    """Save sent article links"""
    sent = load_sent_articles()
    sent.update(article_links)
    
    # Keep only last 7 days worth (prevent file bloat)
    sent = list(sent)[-500:]  # Arbitrary limit
    
    with open('sent_articles.json', 'w') as f:
        json.dump(list(sent), f)

def main():
    print(f"Running digest scraper at {datetime.now()}")
    
    all_articles = []
    
    # Fetch from all sources
    for source_name, url in SOURCES.items():
        print(f"Fetching {source_name}...")
        articles = fetch_rss_articles(url, source_name)
        all_articles.extend(articles)
    
    print(f"Total articles fetched: {len(all_articles)}")
    
    # Filter and score
    filtered_articles = []
    for article in all_articles:
        score = score_article(article)
        if score > 0:  # Only keep articles with positive score
            filtered_articles.append(article)
    
    print(f"Articles after filtering: {len(filtered_articles)}")
    
    # Remove duplicates based on already-sent articles
    sent_links = load_sent_articles()
    new_articles = [a for a in filtered_articles if a['link'] not in sent_links]
    
    print(f"New articles (not previously sent): {len(new_articles)}")
    
    # Sort by score (highest first)
    new_articles.sort(key=lambda x: x['score'], reverse=True)
    
    # Take top 5 articles
    top_articles = new_articles[:5]
    
    if not top_articles:
        print("No new articles to send today")
        return
    
    print(f"\nSending {len(top_articles)} articles:")
    for article in top_articles:
        print(f"  - {article['title']} (score: {article['score']})")
    
    # Send email
    success = send_email(top_articles, 'joshjdi24@gmail.com')
    
    if success:
        # Save sent article links
        sent_links = [a['link'] for a in top_articles]
        save_sent_articles(sent_links)
        print("✓ Digest sent successfully")
    else:
        print("✗ Failed to send digest")

if __name__ == '__main__':
    main()
