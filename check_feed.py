import json
import os
import requests
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

RSS_URL = "https://www.thefantasyfootballers.com/feed/recent_news/"

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")

STATE_FILE = "last_seen.json"
MAX_ITEMS = 500

if not WEBHOOK_URL:
    raise ValueError("DISCORD_WEBHOOK is not set")


# ----------------------------
# STATE
# ----------------------------
def load_seen():
    if not os.path.exists(STATE_FILE):
        return [], set(), set()

    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            ids = data.get("seen_ids", [])
            urls = data.get("seen_urls", [])
            return ids, set(ids), set(urls)
    except:
        return [], set(), set()


def save_seen(ids, urls):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({
            "seen_ids": ids,
            "seen_urls": list(urls)
        }, f)
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
        items.append({
            "title": item.findtext("title"),
            "link": item.findtext("link"),
            "guid": item.findtext("guid") or item.findtext("link"),
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

    seen_ids, seen_id_set, seen_url_set = load_seen()

    new_items = []

    for item in items:
        if (
            item["guid"] not in seen_id_set and
            item["link"] not in seen_url_set
        ):
            new_items.append(item)

    if not new_items:
        print("No new articles.")
        return

    new_items.reverse()

    updated = False

    for item in new_items:
        title = item["title"] or "No title"
        link = item["link"]
        guid = item["guid"]

        time_str = format_time(item["pub_date"])

        success = send_to_discord(title, link, time_str)

        if success:
            seen_ids.append(guid)
            seen_id_set.add(guid)
            seen_url_set.add(link)
            updated = True
        else:
            print("Will retry next run")

        time.sleep(1)

    if len(seen_ids) > MAX_ITEMS:
        seen_ids = seen_ids[-MAX_ITEMS:]

    if updated:
        save_seen(seen_ids, seen_url_set)

    print("---- RUN END ----")


if __name__ == "__main__":
    main()
