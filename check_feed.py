import json
import os
import requests
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

RSS_URL = "https://www.thefantasyfootballers.com/feed/recent_news/"

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")

STATE_FILE = "last_seen.json"
MAX_ITEMS = 500
MAX_POSTS_PER_RUN = 5

if not WEBHOOK_URL:
    raise ValueError("DISCORD_WEBHOOK is not set")


# ----------------------------
# KEY EXTRACTION
# ----------------------------
def extract_key(link):
    try:
        path = urlparse(link).path.strip("/")
        if path.startswith("news/"):
            return path.replace("news/", "").rstrip("/")
    except:
        pass
    return link  # fallback


# ----------------------------
# STATE
# ----------------------------
def load_seen():
    if not os.path.exists(STATE_FILE):
        return [], set()

    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            seen_list = data.get("seen", [])
            return seen_list, set(seen_list)
    except:
        return [], set()


def save_seen(seen_list):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"seen": seen_list}, f, indent=2)
    os.replace(tmp, STATE_FILE)


# ----------------------------
# RSS
# ----------------------------
def fetch_rss():
    r = requests.get(RSS_URL, timeout=10)
    r.raise_for_status()
    return r.content


def parse_rss(xml_data):
    root = ET.fromstring(xml_data)
    items = []

    for item in root.findall(".//item"):
        link = item.findtext("link")
        key = extract_key(link)

        items.append({
            "title": item.findtext("title"),
            "link": link,
            "key": key,
            "pub_date": item.findtext("pubDate")
        })

    return items


# ----------------------------
# TIME FORMAT
# ----------------------------
def format_time(pub_date):
    try:
        dt = parsedate_to_datetime(pub_date)
        local = dt.astimezone()
        return local.strftime("%B %d, %Y %I:%M %p")
    except:
        return "Unknown time"


# ----------------------------
# DISCORD
# ----------------------------
def send_to_discord(title, link, time_str):
    payload = {
        "thread_name": title[:100],
        "content": f"{time_str}\n{link}"
    }

    MAX_RETRIES = 3

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(WEBHOOK_URL, json=payload, timeout=10)

            if r.status_code == 429:
                retry = float(r.json().get("retry_after", 1))
                print(f"[{attempt}] Rate limited, waiting {retry}s")
                time.sleep(retry)
                continue

            if 500 <= r.status_code < 600:
                print(f"[{attempt}] Discord server error {r.status_code}")
                time.sleep(2)
                continue

            if not r.ok:
                raise Exception(f"{r.status_code}: {r.text}")

            print("Posted:", title)
            return True

        except requests.exceptions.RequestException as e:
            print(f"[{attempt}] Network error:", e)
            time.sleep(2)

    return False


# ----------------------------
# MAIN
# ----------------------------
def main():
    print("---- RUN START ----")

    xml_data = fetch_rss()
    items = parse_rss(xml_data)

    seen_list, seen_set = load_seen()

    # ----------------------------
    # FIRST RUN PROTECTION
    # ----------------------------
    if not seen_list:
        print("First run detected — saving current feed without posting")

        for item in items:
            seen_list.append(item["key"])

        save_seen(seen_list)
        return

    # ----------------------------
    # FIND NEW ITEMS
    # ----------------------------
    new_items = []

    for item in items:
        if item["key"] not in seen_set:
            new_items.append(item)

    if not new_items:
        print("No new articles.")
        return

    # Oldest first
    new_items.sort(key=lambda x: x.get("pub_date", ""))

    # Limit per run
    new_items = new_items[:MAX_POSTS_PER_RUN]

    updated = False

    # ----------------------------
    # POST LOOP
    # ----------------------------
    for item in new_items:
        title = item["title"] or "No title"
        link = item["link"]
        key = item["key"]

        time_str = format_time(item["pub_date"])

        success = send_to_discord(title, link, time_str)

        if success:
            seen_list.append(key)
            seen_set.add(key)
            updated = True
        else:
            print("Will retry next run")

        time.sleep(1)

    # Trim old entries
    if len(seen_list) > MAX_ITEMS:
        seen_list = seen_list[-MAX_ITEMS:]

    if updated:
        save_seen(seen_list)

    print("---- RUN END ----")


if __name__ == "__main__":
    main()
