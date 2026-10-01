#!/usr/bin/env python3
"""Refresh the profile's Data Engineering preparation dashboard."""

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlencode
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


def fetch_commits(owner, repo, username, since):
    commits = []
    page = 1
    while True:
        query = urlencode(
            {
                "author": username,
                "since": since.isoformat().replace("+00:00", "Z"),
                "per_page": 100,
                "page": page,
            }
        )
        url = f"https://api.github.com/repos/{owner}/{repo}/commits?{query}"
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "de-prep-dashboard",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
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


def build_markdown(config):
    owner = config["username"]
    local_tz = ZoneInfo(config["timezone"])
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=config["window_days"])
    by_sha = {}
    repository_names = config["repositories"]

    for name in config["repositories"]:
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

    commits = sorted(by_sha.values(), key=lambda commit: (commit["date"], commit["subject"]), reverse=True)
    today = now.astimezone(local_tz).date()
    active_dates = {commit["date"] for commit in commits}
    active_7 = sum(commit["date"] >= today - timedelta(days=6) for commit in commits)
    active_30 = sum(commit["date"] >= today - timedelta(days=29) for commit in commits)

    streak = 0
    day = today
    if day not in active_dates:
        day -= timedelta(days=1)
    while day in active_dates:
        streak += 1
        day -= timedelta(days=1)

    topic_total = Counter(commit["topic"] for commit in commits)
    topic_30 = Counter(
        commit["topic"]
        for commit in commits
        if commit["date"] >= today - timedelta(days=29)
    )
    activity_total = Counter(commit["activity"] for commit in commits)
    topics = config["topics"]

    lines = [
        "## 📚 Data Engineering preparation dashboard",
        "",
        f"Tracked activity from {len(repository_names)} selected repositories · last {config['window_days']} days · all times {config['timezone']}",
        "",
        "Activity reflects matching commits, not skill level or mastery.",
        "",
        "| Measure | Progress |",
        "| --- | ---: |",
        f"| Tracked commits | {len(commits)} |",
        f"| Active preparation days | {len(active_dates)} |",
        f"| Current streak | {streak} days |",
        f"| Commits in last 7 days | {active_7} |",
        f"| Commits in last 30 days | {active_30} |",
        f"| Prep / project commits | {activity_total['prep']} / {activity_total['project']} |",
        "",
        "### Topic activity",
        "",
        f"| Topic | Last {config['window_days']} days | Last 30 days |",
        "| --- | ---: | ---: |",
    ]
    for topic in topics:
        lines.append(f"| {topic} | {topic_total[topic]} | {topic_30[topic]} |")

    lines.extend(["", "### Recent tracked work", ""])
    if commits:
        lines.extend(["| Date | Topic | Type | Work | Repository |", "| --- | --- | --- | --- | --- |"])
        for commit in commits[:8]:
            description = commit["subject"].split("] ", 1)[-1]
            work = f"[{description}]({commit['url']})" if commit["url"] else description
            repo_url = f"https://github.com/{owner}/{commit['repository']}"
            lines.append(
                f"| {commit['date'].isoformat()} | {commit['topic']} | {commit['activity']} | {work} | [{commit['repository']}]({repo_url}) |"
            )
    else:
        lines.append("No matching commits yet. Use the format below in a tracked repository to start the dashboard.")
    lines.extend(
        [
            "",
            "Commit format: `de(<topic>): [<prep|project>] <short description>` · [tracked repositories and setup](https://github.com/minhazalam/minhazalam/tree/main/de-prep)",
        ]
    )
    return "\n".join(lines)


def update_readme(markdown):
    readme = README_PATH.read_text(encoding="utf-8")
    section = f"{START}\n{markdown}\n{END}"
    start_index = readme.find(START)
    end_index = readme.find(END)
    if start_index >= 0 and end_index > start_index:
        updated = readme[:start_index] + section + readme[end_index + len(END) :]
    else:
        updated = readme.rstrip() + "\n\n" + section + "\n"
    README_PATH.write_text(updated, encoding="utf-8")


def main():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    update_readme(build_markdown(config))


if __name__ == "__main__":
    main()
