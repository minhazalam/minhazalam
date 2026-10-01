#!/usr/bin/env python3
"""Refresh the profile Data Engineering preparation dashboard."""

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(__file__).with_name("tracked-repositories.json")
README_PATH = ROOT / "README.md"
START = "<!-- DE-PREP-DASHBOARD:START -->"
END = "<!-- DE-PREP-DASHBOARD:END -->"
SUBJECT = re.compile(
    r"^de\((python|sql|dsa|pyspark|kafka|databricks|system-design)\): "
    r"\[(prep|project)\] (\S(?:.*\S)?)$"
)
TOPIC_DISPLAY = {
    "python": ("🐍", "Python"),
    "sql": ("🧮", "SQL"),
    "dsa": ("🧩", "DSA"),
    "pyspark": ("⚡", "PySpark"),
    "kafka": ("📨", "Kafka"),
    "databricks": ("🧱", "Databricks"),
    "system-design": ("🏗️", "System design"),
}


def fetch_commits(owner, repo, username, since):
    commits = []
    page = 1
    while True:
        query = urlencode({
            "author": username,
            "since": since.isoformat().replace("+00:00", "Z"),
            "per_page": 100,
            "page": page,
        })
        url = f"https://api.github.com/repos/{owner}/{repo}/commits?{query}"
        request = Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "de-prep-dashboard",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        try:
            with urlopen(request, timeout=30) as response:
                batch = json.load(response)
        except HTTPError as error:
            raise RuntimeError(
                f"GitHub API request failed for {owner}/{repo}: HTTP {error.code}"
            ) from error
        if not batch:
            break
        commits.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return commits


def badge(label, value, color):
    label_part = quote(label, safe="")
    value_part = quote(str(value), safe="")
    url = f"https://img.shields.io/badge/{label_part}-{value_part}-{color}?style=flat-square"
    return f"![{label}: {value}]({url})"


def build_markdown(config):
    owner = config["username"]
    local_tz = ZoneInfo(config["timezone"])
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=config["window_days"])
    by_sha = {}
    repository_names = config["repositories"]

    for name in repository_names:
        for item in fetch_commits(owner, name, owner, since):
            author = item.get("author") or {}
            if author.get("login", "").casefold() != owner.casefold():
                continue
            message = item.get("commit", {}).get("message", "")
            subject = message.splitlines()[0] if message else ""
            match = SUBJECT.fullmatch(subject)
            if not match:
                continue
            authored = item.get("commit", {}).get("author", {}).get("date")
            if not authored:
                continue
            commit_time = datetime.fromisoformat(authored.replace("Z", "+00:00"))
            by_sha[item["sha"]] = {
                "date": commit_time.astimezone(local_tz).date(),
                "topic": match.group(1),
                "activity": match.group(2),
                "subject": subject,
                "repository": name,
                "url": item.get("html_url", ""),
            }

    commits = sorted(
        by_sha.values(),
        key=lambda commit: (commit["date"], commit["subject"]),
        reverse=True,
    )
    today = now.astimezone(local_tz).date()
    active_dates = {commit["date"] for commit in commits}
    last_7 = sum(commit["date"] >= today - timedelta(days=6) for commit in commits)
    last_30 = sum(commit["date"] >= today - timedelta(days=29) for commit in commits)

    streak = 0
    day = today if today in active_dates else today - timedelta(days=1)
    while day in active_dates:
        streak += 1
        day -= timedelta(days=1)

    topic_total = Counter(commit["topic"] for commit in commits)
    activity_total = Counter(commit["activity"] for commit in commits)
    topics = config["topics"]


    lines = [
        "## 📊 Data Engineering preparation",
        "",
        f"> Commit activity across {len(repository_names)} selected repositories · last {config['window_days']} days · {config['timezone']}. Activity indicates logged work, not skill or mastery.",
        "",
        " ".join([
            badge("Commits", len(commits), "2F81F7"),
            badge("Active days", len(active_dates), "238636"),
            badge("Streak", f"{streak} days", "BD561D"),
            badge("Last 30 days", last_30, "8957E5"),
        ]),
        "",
        f"### Topic activity · last {config['window_days']} days",
        "",
    ]
    topic_colors = {
        "python": "2F81F7",
        "sql": "238636",
        "dsa": "8957E5",
        "pyspark": "BD561D",
        "kafka": "0E8A16",
        "databricks": "E36209",
        "system-design": "8250DF",
    }
    lines.append(" ".join(
        badge(TOPIC_DISPLAY[topic][1], topic_total[topic], topic_colors[topic])
        for topic in topics
    ))
    lines.extend([
        "",
        "*Topic counts are matching commits, not proficiency.*",
        "",
        "### Recent work",
        "",
    ])
    if commits:
        for commit in commits[:8]:
            _, label = TOPIC_DISPLAY[commit["topic"]]
            description = commit["subject"].split("] ", 1)[-1]
            work = f"[{description}]({commit['url']})" if commit["url"] else description
            repo_url = f"https://github.com/{owner}/{commit['repository']}"
            lines.append(
                f"- **{commit['date'].isoformat()} · {label} · {commit['activity']}** — "
                f"{work} · [{commit['repository']}]({repo_url})"
            )
    else:
        lines.append("_No matching commits yet._ Start with the format below in a tracked repository.")
    lines.extend([
        "",
        "Commit format: `de(python): [prep] solve two sum with hash map` · "
        f"[repositories and setup](https://github.com/{owner}/{owner}/tree/main/de-prep)",
    ])
    return "\n".join(lines)


def update_readme(markdown):
    readme = README_PATH.read_text(encoding="utf-8")
    section = f"{START}\n{markdown}\n{END}"
    start_index = readme.find(START)
    end_index = readme.find(END)
    if start_index >= 0 and end_index > start_index:
        updated = readme[:start_index] + section + readme[end_index + len(END):]
    else:
        updated = readme.rstrip() + "\n\n" + section + "\n"
    README_PATH.write_text(updated, encoding="utf-8")


def main():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    update_readme(build_markdown(config))


if __name__ == "__main__":
    main()
