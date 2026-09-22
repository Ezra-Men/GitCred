from collections import Counter
from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Optional
import httpx

GITHUB_API_BASE = 'https://api.github.com'


class GitHubServiceError(Exception):
  """Custom exception for GitHub API failures."""

  pass


class GitHubService:

  def __init__(self, token: Optional[str] = None):
    self.token = token or os.getenv('GITHUB_TOKEN')
    self.headers = {
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    if self.token:
      self.headers['Authorization'] = f'Bearer {self.token}'

  def fetch_user_data(self, username: str) -> Dict[str, Any]:
    """Fetches user profile, public repositories, and recent events,

    returning a consolidated metrics payload for AI analysis.
    """
    clean_username = username.strip().lstrip('@')

    with httpx.Client(
        base_url=GITHUB_API_BASE, headers=self.headers, timeout=12.0
    ) as client:
      # 1. Fetch Profile
      user_resp = client.get(f'/users/{clean_username}')
      if user_resp.status_code == 404:
        raise GitHubServiceError(
            f"GitHub user '{clean_username}' was not found."
        )
      elif user_resp.status_code == 403 or user_resp.status_code == 429:
        raise GitHubServiceError('GitHub API rate limit exceeded.')
      elif user_resp.status_code != 200:
        raise GitHubServiceError(
            f'GitHub API error ({user_resp.status_code}): {user_resp.text}'
        )

      user_data = user_resp.json()

      # 2. Fetch Up to 30 Most Recently Updated Public Repos
      repos_resp = client.get(
          f'/users/{clean_username}/repos',
          params={'sort': 'updated', 'per_page': 30, 'type': 'owner'},
      )
      repos_data = repos_resp.json() if repos_resp.status_code == 200 else []

      # 3. Fetch Recent Public Events (Commit activity proxy)
      events_resp = client.get(
          f'/users/{clean_username}/events/public', params={'per_page': 50}
      )
      events_data = (
          events_resp.json() if events_resp.status_code == 200 else []
      )

    return self._process_metrics(user_data, repos_data, events_data)

  def _process_metrics(
      self,
      user: Dict[str, Any],
      repos: List[Dict[str, Any]],
      events: List[Dict[str, Any]],
  ) -> Dict[str, Any]:
    """Summarizes raw payloads into a compact format to minimize LLM token usage."""
    language_counter = Counter()
    total_stars = 0
    total_forks = 0
    repo_summaries = []

    for r in repos:
      if r.get('fork', False):
        continue  # Skip forked repositories to evaluate original work

      lang = r.get('language')
      if lang:
        language_counter[lang] += 1

      stars = r.get('stargazers_count', 0)
      forks = r.get('forks_count', 0)
      total_stars += stars
      total_forks += forks

      repo_summaries.append({
          'name': r.get('name'),
          'description': r.get('description') or 'No description provided',
          'language': lang,
          'stars': stars,
          'topics': r.get('topics', []),
          'pushed_at': r.get('pushed_at'),
      })

    # Top 8 repos by star count / freshness
    top_repos = sorted(repo_summaries, key=lambda x: x['stars'], reverse=True)[
        :8
    ]

    # Calculate recent commit cadence from public PushEvents
    push_events = [e for e in events if e.get('type') == 'PushEvent']
    recent_commits_count = sum(
        len(e.get('payload', {}).get('commits', [])) for e in push_events
    )

    return {
        'profile': {
            'username': user.get('login'),
            'name': user.get('name'),
            'avatar_url': user.get('avatar_url'),
            'bio': user.get('bio'),
            'location': user.get('location'),
            'public_repos_count': user.get('public_repos', 0),
            'followers_count': user.get('followers', 0),
            'created_at': user.get('created_at'),
        },
        'stats': {
            'original_repos_analyzed': len(repo_summaries),
            'total_stars_earned': total_stars,
            'total_forks_earned': total_forks,
            'primary_languages': [lang for lang, _ in language_counter.most_common(5)],
            'recent_public_commits': recent_commits_count,
        },
        'notable_repositories': top_repos,
    }

