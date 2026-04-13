#!/usr/bin/env python3
"""
Product Hunt Weekly Top 5 Analyzer
Fetches top 5 products from Product Hunt, analyzes with Claude AI, posts to Slack
"""

import os
import json
import requests
from datetime import datetime, timedelta
from anthropic import Anthropic

# Initialize Anthropic client
client = Anthropic()

def get_producthunt_token():
    """Get Product Hunt API token using client credentials"""
    client_id = os.getenv("PRODUCTHUNT_CLIENT_ID")
    client_secret = os.getenv("PRODUCTHUNT_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        raise ValueError("Missing PRODUCTHUNT_CLIENT_ID or PRODUCTHUNT_CLIENT_SECRET")
    
    response = requests.post(
        "https://api.producthunt.com/v2/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials"
        }
    )
    
    if response.status_code != 200:
        raise Exception(f"Failed to get Product Hunt token: {response.text}")
    
    return response.json()["access_token"]

def fetch_producthunt_top_products(limit=5):
    """Fetch top products from Product Hunt for the current week"""
    token = get_producthunt_token()
    
    # GraphQL query for top posts
    query = """
    query {
        posts(order: VOTES, first: %d) {
            edges {
                node {
                    id
                    name
                    tagline
                    description
                    url
                    votesCount
                    commentsCount
                    reviewsCount
                    reviewsRating
                    createdAt
                    thumbnail {
                        url
                    }
                }
            }
        }
    }
    """ % limit
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    response = requests.post(
        "https://api.producthunt.com/v2/api/graphql",
        json={"query": query},
        headers=headers
    )
    
    if response.status_code != 200:
        raise Exception(f"Failed to fetch from Product Hunt: {response.text}")
    
    data = response.json()
    
    if "errors" in data:
        raise Exception(f"GraphQL error: {data['errors']}")
    
    products = []
    for edge in data["data"]["posts"]["edges"]:
        node = edge["node"]
        products.append({
            "name": node["name"],
            "tagline": node["tagline"],
            "description": node["description"],
            "url": node["url"],
            "votes": node["votesCount"],
            "comments": node["commentsCount"],
            "reviews_count": node["reviewsCount"],
            "rating": node["reviewsRating"],
            "created_at": node["createdAt"],
            "thumbnail": node["thumbnail"]["url"] if node["thumbnail"] else None
        })
    
    return products

def analyze_with_claude(products):
    """Use Claude to analyze why these products are trending and provide insights"""
    
    # Format products data for Claude
    products_text = "\n".join([
        f"{i+1}. {p['name']} ({p['votes']} votes, Rating: {p['rating']}/5)\n"
        f"   Tagline: {p['tagline']}\n"
        f"   Description: {p['description'][:150]}...\n"
        f"   URL: {p['url']}"
        for i, p in enumerate(products)
    ])
    
    prompt = f"""Analyze these top 5 products from Product Hunt this week and provide:

1. **Trend Analysis**: What trends/patterns do you see? What's driving votes?
2. **Rating Insights**: Focus on the review ratings - which ones have strong community validation?
3. **Investment Potential**: Based on votes, comments, and ratings, which are most promising?
4. **Key Takeaways**: 2-3 key insights about what's trending in tech this week

Products:
{products_text}

Format your response in clear sections with actionable insights. Keep it concise but comprehensive."""
    
    message = client.messages.create(
        model="claude-sonnet-4",
        max_tokens=1024,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    return message.content[0].text

def convert_markdown_to_slack(text):
    """Convert markdown formatting to Slack mrkdwn format"""
    # Replace markdown bold (**text**) with Slack bold (*text*)
    text = text.replace("**", "*")
    # Replace markdown headers with bold (## text -> *text*)
    text = text.replace("## ", "*")
    # Ensure proper line spacing
    text = text.strip()
    return text

def format_slack_message(products, analysis):
    """Format the data into a Slack message with blocks"""
    
    # Build product list blocks
    product_blocks = []
    for i, p in enumerate(products, 1):
        rating_emoji = "⭐" * int(p["rating"] or 0) if p["rating"] else "unrated"
        
        product_blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*#{i}. {p['name']}*\n"
                       f"_{p['tagline']}_\n"
                       f"🔥 {p['votes']:,} votes | {rating_emoji} ({p['rating']}/5 from {p['reviews_count']} reviews) | 💬 {p['comments']} comments\n"
                       f"<{p['url']}|View on Product Hunt>"
            }
        })
        product_blocks.append({"type": "divider"})
    
    # Remove last divider
    if product_blocks:
        product_blocks.pop()
    
    # Split analysis into sections for better readability
    analysis_sections = analysis.split("\n\n")
    
    # Build final message blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📊 Product Hunt Weekly Top 5"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Week of {datetime.now().strftime('%B %d, %Y')} | AI-powered analysis by Claude"
                }
            ]
        },
        {"type": "divider"},
        *product_blocks,
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*📈 AI Analysis & Insights*\n\n{convert_markdown_to_slack(analysis)}"
            }
        }
    ]
    
    return {"blocks": blocks}

def post_to_slack(message):
    """Post formatted message to Slack webhook"""
    slack_webhook = os.getenv("SLACK_WEBHOOK_URL")
    
    if not slack_webhook:
        raise ValueError("Missing SLACK_WEBHOOK_URL environment variable")
    
    response = requests.post(slack_webhook, json=message)
    
    if response.status_code != 200:
        raise Exception(f"Failed to post to Slack: {response.text}")
    
    print("✅ Successfully posted to Slack!")
    return response

def main():
    """Main execution"""
    try:
        print("🚀 Starting Product Hunt Weekly Analysis...")
        
        # Fetch products
        print("📥 Fetching top 5 products from Product Hunt...")
        products = fetch_producthunt_top_products(limit=5)
        
        print(f"✅ Found {len(products)} products")
        for p in products:
            print(f"   - {p['name']} ({p['votes']} votes)")
        
        # Analyze with Claude
        print("\n🤖 Analyzing with Claude AI...")
        analysis = analyze_with_claude(products)
        
        # Format for Slack
        print("📝 Formatting Slack message...")
        slack_message = format_slack_message(products, analysis)
        
        # Post to Slack
        print("📤 Posting to Slack...")
        post_to_slack(slack_message)
        
        print("\n✨ All done!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        raise

if __name__ == "__main__":
    main()
