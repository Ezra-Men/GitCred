from django.shortcuts import render

# Create your views here.
from django.shortcuts import render

# Create your views here.
from datetime import timedelta
from django.core.cache import cache
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .models import TalentProfile
from .services.ai_service import AIService, AIServiceError
from .services.github_service import GitHubService, GitHubServiceError
from django.http import HttpResponse

def index_view(request):
  """Page 1: Search landing page + featured audit demo chips."""
  featured_profiles = TalentProfile.objects.all().order_by('-updated_at')[:4]
  return render(
      request, 'core/index.html', {'featured_profiles': featured_profiles}
  )


def audit_user_view(request):
  if request.method != "POST":
    return redirect("core:index")

  raw_input = request.POST.get("username", "").strip()

  # Automatically strip URLs or @ handles (e.g., https://github.com/EZRA-MEN/ -> EZRA-MEN)
  username = raw_input.rstrip("/").split("/")[-1].lstrip("@").strip()

  if not username:
    return render(
        request,
        "core/index.html",
        {"error": "Please provide a valid GitHub username or profile link."},
    )

  # 1. IP Throttling: Max 5 new audits per minute per IP
  ip_address = request.META.get('REMOTE_ADDR', 'unknown')
  rate_limit_key = f'audit_rate_{ip_address}'
  audit_count = cache.get(rate_limit_key, 0)

  if audit_count >= 5:
    return render(
        request,
        'core/index.html',
        {
            'error': (
                'Rate limit exceeded. Please wait a minute before analyzing'
                ' another profile.'
            )
        },
    )

  # 2. Database Cache Check (Avoid re-hitting APIs if audited in the last 24 hours)
  one_day_ago = timezone.now() - timedelta(hours=24)
  existing_profile = TalentProfile.objects.filter(
      username__iexact=username, updated_at__gte=one_day_ago
  ).first()

  if existing_profile:
    return redirect('core:passport', username=existing_profile.username)

  # 3. Fetch from GitHub & Run AI Audit
  try:
    gh_service = GitHubService()
    gh_data = gh_service.fetch_user_data(username)

    ai_service = AIService()
    evaluation = ai_service.evaluate_developer(gh_data)

    # 4. Persist / Update Candidate Profile
    profile, _ = TalentProfile.objects.update_or_create(
        username=gh_data['profile']['username'],
        defaults={
            'name': gh_data['profile']['name'] or username,
            'avatar_url': gh_data['profile']['avatar_url'],
            'bio': gh_data['profile']['bio'],
            'location': gh_data['profile']['location'],
            'public_repos_count': gh_data['profile']['public_repos_count'],
            'followers_count': gh_data['profile']['followers_count'],
            'primary_role': evaluation.primary_role,
            'seniority_level': evaluation.seniority_level,
            'confidence_score': evaluation.confidence_score,
            'top_skills': evaluation.top_skills,
            'metrics_signals': evaluation.metrics_signals.model_dump(),
            'summary': evaluation.summary,
        },
    )

    # Increment throttle count with a 60-second expiration
    cache.set(rate_limit_key, audit_count + 1, timeout=60)

    return redirect('core:passport', username=profile.username)

  except (GitHubServiceError, AIServiceError) as err:
    return render(request, 'core/index.html', {'error': str(err)})


def passport_view(request, username):
  """Page 2: The shareable Talent Passport."""
  profile = get_object_or_404(TalentProfile, username__iexact=username)
  return render(request, 'core/passport.html', {'profile': profile})


def badge_view(request, username):
  """Returns a dynamic SVG badge for README markdown embedding."""
  clean_username = username.strip().lstrip('@')
  profile = TalentProfile.objects.filter(username__iexact=clean_username).first()

  if profile:
    role = profile.primary_role
    tier = profile.get_seniority_level_display()
    badge_label = f'{role} • {tier}'
    status_color = (
        '#10b981'
        if profile.seniority_level == 'SENIOR'
        else ('#6366f1' if profile.seniority_level == 'MID' else '#f59e0b')
    )
  else:
    badge_label = 'Candidate Not Audited'
    status_color = '#64748b'

  # Approximate SVG width based on character length
  text_length = len(badge_label)
  total_width = 110 + (text_length * 7)
  status_x = 100 + ((total_width - 100) / 2)

  svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="24" viewBox="0 0 {total_width} 24">
    <linearGradient id="b" x2="0" y2="100%">
      <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
      <stop offset="1" stop-opacity=".1"/>
    </linearGradient>
    <clipPath id="a">
      <rect width="{total_width}" height="24" rx="4" fill="#fff"/>
    </clipPath>
    <g clip-path="url(#a)">
      <rect width="90" height="24" fill="#0f172a"/>
      <rect x="90" width="{total_width - 90}" height="24" fill="{status_color}"/>
      <rect width="{total_width}" height="24" fill="url(#b)"/>
    </g>
    <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
      <text x="45" y="16" fill="#fff" font-weight="bold">AfroPass</text>
      <text x="{status_x}" y="16" fill="#fff" font-weight="bold">{badge_label}</text>
    </g>
  </svg>"""

  return HttpResponse(svg_content, content_type='image/svg+xml')