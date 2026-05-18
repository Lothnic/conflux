"""
Conflux Reddit Ingestor - r/delhi Only
Fetches hot threads from r/delhi and saves them locally.
Author: Lothnic
"""
import praw
import json
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv


load_dotenv()


def get_reddit_instance():
    """Create and return a PRAW Reddit instance."""
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    user_agent = os.getenv("REDDIT_USER_AGENT", "Conflux:1.0")

    if not client_id or not client_secret:
        raise ValueError(
            "Missing Reddit API credentials. "
            "Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env"
        )

    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )


def fetch_hot_threads(reddit, subreddit_name="delhi", limit=50):
    """Fetch hot threads from a subreddit."""
    subreddit = reddit.subreddit(subreddit_name)
    threads = []
    for submission in subreddit.hot(limit=limit):
        threads.append({
            "id": submission.id,
            "title": submission.title,
            "url": submission.url,
            "author": submission.author.name if submission.author else "[deleted]",
            "created_utc": datetime.fromtimestamp(submission.created_utc).isoformat(),
            "upvotes": submission.upvotes,
            "num_comments": submission.num_comments,
            "flair": submission.link_flair_text or "",
            "content": submission.selftext[:500] if submission.selftext else "",
        })
    return threads


def fetch_top_threads(reddit, subreddit_name="delhi", limit=50):
    """Fetch top threads from a subreddit."""
    subreddit = reddit.subreddit(subreddit_name)
    threads = []
    for submission in subreddit.top(limit=limit):
        threads.append({
            "id": submission.id,
            "title": submission.title,
            "url": submission.url,
            "author": submission.author.name if submission.author else "[deleted]",
            "created_utc": datetime.fromtimestamp(submission.created_utc).isoformat(),
            "upvotes": submission.upvotes,
            "num_comments": submission.num_comments,
            "flair": submission.link_flair_text or "",
            "content": submission.selftext[:500] if submission.selftext else "",
        })
    return threads


def fetch_comments(reddit, thread_id, limit=100):
    """Fetch comments for a specific thread."""
    submission = reddit.submission(id=thread_id)
    submission.comments.replace_more(limit=0)
    comments = []
    for comment in submission.comments[:limit]:
        comments.append({
            "id": comment.id,
            "body": comment.body[:500],
            "author": comment.author.name if comment.author else "[deleted]",
            "created_utc": datetime.fromtimestamp(comment.created_utc).isoformat(),
            "upvotes": comment.upvotes,
        })
    return comments


def save_to_file(data, filename="reddit_data.json"):
    """Save threads/comments to a JSON file."""
    output_dir = Path("data")
    output_dir.mkdir(exist_ok=True)
    filepath = output_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(data)} items to {filepath}")


def main():
    """Main entry point."""
    reddit = get_reddit_instance()
    print("Fetching hot threads from r/delhi...")
    threads = fetch_hot_threads(reddit, subreddit_name="delhi", limit=50)
    save_to_file(threads, "reddit_hot_threads.json")

    print("\nFetching top threads from r/delhi...")
    top_threads = fetch_top_threads(reddit, subreddit_name="delhi", limit=20)
    save_to_file(top_threads, "reddit_top_threads.json")

    print("\nFetching comments for first thread...")
    if top_threads:
        comments = fetch_comments(reddit, top_threads[0]["id"], limit=100)
        save_to_file(comments, f"comments_{top_threads[0]['id']}.json")


if __name__ == "__main__":
    main()
