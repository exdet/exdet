#!/usr/bin/env python3
"""Generate a GitHub language-stat SVG from all repositories visible to a token.

The script intentionally does not write repository names into the SVG.
This keeps private repository names out of the public profile README.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_ROOT = "https://api.github.com"
OUTPUT_SVG = Path(os.getenv("OUTPUT_SVG", "assets/languages.svg"))
OUTPUT_JSON = Path(os.getenv("OUTPUT_JSON", "assets/languages.json"))
WRITE_JSON = os.getenv("WRITE_JSON", "false").lower() == "true"

LANGUAGE_COLORS: dict[str, str] = {
    "Rust": "#dea584",
    "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a",
    "Python": "#3572A5",
    "Go": "#00ADD8",
    "C": "#555555",
    "C++": "#f34b7d",
    "C#": "#178600",
    "Java": "#b07219",
    "Kotlin": "#A97BFF",
    "Shell": "#89e051",
    "PowerShell": "#012456",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "SCSS": "#c6538c",
    "Vue": "#41b883",
    "Svelte": "#ff3e00",
    "PHP": "#4F5D95",
    "Ruby": "#701516",
    "Dart": "#00B4AB",
    "Swift": "#F05138",
    "Objective-C": "#438eff",
    "Lua": "#000080",
    "Dockerfile": "#384d54",
    "Makefile": "#427819",
    "CMake": "#DA3434",
    "SQL": "#e38c00",
    "PLpgSQL": "#336790",
    "Jupyter Notebook": "#DA5B0B",
    "Other": "#8b949e",
}

@dataclass(frozen=True)
class RepoFilter:
    affiliation: str
    include_private: bool
    include_forks: bool
    include_archived: bool
    exclude_current_repo: bool
    exclude_repos: set[str]


def bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def token() -> str:
    value = os.getenv("GH_STATS_TOKEN")
    if not value:
        raise RuntimeError(
            "GH_STATS_TOKEN is missing. Add a repository secret named GH_STATS_TOKEN. "
            "Do not use the default GITHUB_TOKEN for cross-repository stats."
        )
    return value


def headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token()}",
        "X-GitHub-Api-Version": os.getenv("GITHUB_API_VERSION", "2022-11-28"),
        "User-Agent": "profile-language-stats-generator",
    }


def github_get(path_or_url: str, params: dict[str, Any] | None = None) -> tuple[Any, dict[str, str]]:
    if path_or_url.startswith("https://"):
        url = path_or_url
    else:
        url = f"{API_ROOT}{path_or_url}"

    if params:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urlencode(params)}"

    request = Request(url, headers=headers(), method="GET")
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body) if body else None
            return data, dict(response.headers.items())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API error {exc.code} for {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error for {url}: {exc}") from exc


def parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip().split(";")
        if len(section) < 2:
            continue
        url_part = section[0].strip()
        rel_part = ";".join(section[1:]).strip()
        if 'rel="next"' in rel_part and url_part.startswith("<") and url_part.endswith(">"):
            return url_part[1:-1]
    return None


def paginated_get(path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    next_url: str | None = f"{API_ROOT}{path}?{urlencode(params)}"
    while next_url:
        data, response_headers = github_get(next_url)
        if not isinstance(data, list):
            raise RuntimeError(f"Expected list from {path}, got {type(data).__name__}")
        items.extend(data)
        next_url = parse_next_link(response_headers.get("Link"))
    return items


def get_repo_filter() -> RepoFilter:
    exclude_raw = os.getenv("EXCLUDE_REPOS", "")
    exclude_repos = {item.strip().lower() for item in exclude_raw.split(",") if item.strip()}

    current_repo = os.getenv("GITHUB_REPOSITORY", "").strip().lower()
    exclude_current_repo = bool_env("EXCLUDE_CURRENT_REPO", True)
    if exclude_current_repo and current_repo:
        exclude_repos.add(current_repo)

    return RepoFilter(
        affiliation=os.getenv("REPO_AFFILIATION", "owner,collaborator,organization_member"),
        include_private=bool_env("INCLUDE_PRIVATE", True),
        include_forks=bool_env("INCLUDE_FORKS", False),
        include_archived=bool_env("INCLUDE_ARCHIVED", True),
        exclude_current_repo=exclude_current_repo,
        exclude_repos=exclude_repos,
    )


def should_count_repo(repo: dict[str, Any], repo_filter: RepoFilter) -> bool:
    full_name = str(repo.get("full_name", "")).lower()
    if full_name in repo_filter.exclude_repos:
        return False
    if repo.get("fork") and not repo_filter.include_forks:
        return False
    if repo.get("archived") and not repo_filter.include_archived:
        return False
    if repo.get("private") and not repo_filter.include_private:
        return False
    return True


def list_repositories(repo_filter: RepoFilter) -> list[dict[str, Any]]:
    params = {
        "per_page": 100,
        "visibility": "all" if repo_filter.include_private else "public",
        "affiliation": repo_filter.affiliation,
        "sort": "updated",
        "direction": "desc",
    }
    return paginated_get("/user/repos", params)


def collect_language_bytes(repositories: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    totals: dict[str, int] = {}
    counters = {
        "repositories_scanned": 0,
        "repositories_with_languages": 0,
        "private_repositories_scanned": 0,
    }

    for repo in repositories:
        counters["repositories_scanned"] += 1
        if repo.get("private"):
            counters["private_repositories_scanned"] += 1

        languages_url = repo.get("languages_url")
        if not languages_url:
            continue

        data, _ = github_get(str(languages_url))
        if not isinstance(data, dict):
            continue
        if data:
            counters["repositories_with_languages"] += 1

        for language, byte_count in data.items():
            if not isinstance(language, str):
                continue
            try:
                value = int(byte_count)
            except (TypeError, ValueError):
                continue
            if value > 0:
                totals[language] = totals.get(language, 0) + value

        time.sleep(0.04)

    return totals, counters


def deterministic_color(language: str) -> str:
    if language in LANGUAGE_COLORS:
        return LANGUAGE_COLORS[language]
    value = sum((index + 1) * ord(char) for index, char in enumerate(language))
    hue = value % 360
    return hsl_to_hex(hue, 58, 62)


def hsl_to_hex(h: int, s: int, l: int) -> str:
    s_f = s / 100
    l_f = l / 100
    c = (1 - abs(2 * l_f - 1)) * s_f
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l_f - c / 2
    if 0 <= h < 60:
        r, g, b = c, x, 0
    elif 60 <= h < 120:
        r, g, b = x, c, 0
    elif 120 <= h < 180:
        r, g, b = 0, c, x
    elif 180 <= h < 240:
        r, g, b = 0, x, c
    elif 240 <= h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return "#{:02x}{:02x}{:02x}".format(
        round((r + m) * 255), round((g + m) * 255), round((b + m) * 255)
    )


def human_bytes(value: int) -> str:
    if value <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    index = min(int(math.log(value, 1024)), len(units) - 1)
    scaled = value / (1024 ** index)
    if index == 0:
        return f"{value} B"
    return f"{scaled:.1f} {units[index]}"


def compact_languages(language_bytes: dict[str, int], max_languages: int) -> list[tuple[str, int]]:
    ordered = sorted(language_bytes.items(), key=lambda item: item[1], reverse=True)
    if len(ordered) <= max_languages:
        return ordered
    visible = ordered[: max_languages - 1]
    other_total = sum(value for _, value in ordered[max_languages - 1 :])
    return visible + [("Other", other_total)]


def render_empty_svg(message: str) -> str:
    title = escape(os.getenv("SVG_TITLE", "Language Stats"))
    msg = escape(message)
    return f'''<svg width="860" height="210" viewBox="0 0 860 210" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">{title}</title>
  <desc id="desc">GitHub repository language statistics.</desc>
  <rect width="860" height="210" rx="22" fill="#0d1117"/>
  <rect x="1" y="1" width="858" height="208" rx="21" stroke="#30363d"/>
  <text x="36" y="58" fill="#f0f6fc" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="28" font-weight="700">{title}</text>
  <text x="36" y="104" fill="#8b949e" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="16">{msg}</text>
  <text x="36" y="146" fill="#8b949e" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="14">Run the GitHub Action after adding GH_STATS_TOKEN.</text>
</svg>
'''


def render_svg(language_bytes: dict[str, int], counters: dict[str, int]) -> str:
    if not language_bytes:
        return render_empty_svg("No language data was found.")

    max_languages = env_int("MAX_LANGUAGES", 8, 3, 12)
    title = escape(os.getenv("SVG_TITLE", "Language Stats"))
    languages = compact_languages(language_bytes, max_languages)
    total = sum(language_bytes.values())
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    width = 860
    header_height = 108
    row_height = 38
    footer_height = 54
    height = header_height + len(languages) * row_height + footer_height
    chart_x = 300
    chart_width = 420
    percent_x = 744
    bytes_x = 808

    parts: list[str] = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">',
        f'  <title id="title">{title}</title>',
        '  <desc id="desc">Language percentages generated from GitHub repositories visible to the configured token.</desc>',
        f'  <rect width="{width}" height="{height}" rx="22" fill="#0d1117"/>',
        f'  <rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="21" stroke="#30363d"/>',
        '  <circle cx="780" cy="54" r="78" fill="#161b22" opacity="0.65"/>',
        f'  <text x="36" y="54" fill="#f0f6fc" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="28" font-weight="700">{title}</text>',
        f'  <text x="36" y="82" fill="#8b949e" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="14">Generated from all repositories visible to the token · {escape(generated)}</text>',
        f'  <text x="36" y="106" fill="#8b949e" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="13">Repos scanned: {counters.get("repositories_scanned", 0)} · with code: {counters.get("repositories_with_languages", 0)} · total: {escape(human_bytes(total))}</text>',
    ]

    y = header_height
    for language, byte_count in languages:
        percent = (byte_count / total) * 100 if total else 0
        bar_width = max(4, round(chart_width * percent / 100))
        color = deterministic_color(language)
        lang = escape(language)
        byte_label = escape(human_bytes(byte_count))
        parts.extend(
            [
                f'  <text x="36" y="{y + 21}" fill="#f0f6fc" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="15" font-weight="600">{lang}</text>',
                f'  <rect x="{chart_x}" y="{y + 6}" width="{chart_width}" height="14" rx="7" fill="#21262d"/>',
                f'  <rect x="{chart_x}" y="{y + 6}" width="{bar_width}" height="14" rx="7" fill="{color}"/>',
                f'  <text x="{percent_x}" y="{y + 20}" fill="#f0f6fc" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="14" font-weight="600" text-anchor="end">{percent:.1f}%</text>',
                f'  <text x="{bytes_x}" y="{y + 20}" fill="#8b949e" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="12" text-anchor="end">{byte_label}</text>',
            ]
        )
        y += row_height

    parts.extend(
        [
            f'  <line x1="36" y1="{height - 42}" x2="824" y2="{height - 42}" stroke="#30363d"/>',
            f'  <text x="36" y="{height - 18}" fill="#8b949e" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="12">Private repository names are not written into this SVG.</text>',
            '</svg>',
            '',
        ]
    )
    return "\n".join(parts)


def main() -> int:
    repo_filter = get_repo_filter()
    try:
        all_repos = list_repositories(repo_filter)
        counted_repos = [repo for repo in all_repos if should_count_repo(repo, repo_filter)]
        language_bytes, counters = collect_language_bytes(counted_repos)
        svg = render_svg(language_bytes, counters)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    OUTPUT_SVG.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_SVG.write_text(svg, encoding="utf-8")

    if WRITE_JSON:
        OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        safe_payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "repositories_scanned": counters.get("repositories_scanned", 0),
            "repositories_with_languages": counters.get("repositories_with_languages", 0),
            "languages": dict(sorted(language_bytes.items(), key=lambda item: item[1], reverse=True)),
        }
        OUTPUT_JSON.write_text(json.dumps(safe_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Updated {OUTPUT_SVG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
