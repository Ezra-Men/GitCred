from datetime import timedelta
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

# Local model imports for profiles and peer endorsements
from .models import ProfileReview, TalentProfile

# Service layer imports for GitHub ingestion and Gemini LLM evaluations
from .services.ai_service import AIService, AIServiceError
from .services.github_service import GitHubService, GitHubServiceError


def index_view(request):
    """
    Renders the single-scroll home/search page.
    
    Handles:
    - Loading instant demo profiles from the database if '?user=<username>' query param exists.
    - Fetching the 3 most recently evaluated profiles to populate the demo chips.
    """
    # 1. Check if the user clicked one of the instant demo chips (e.g. ?user=Ezra-Men)
    username = request.GET.get("user", "").strip()
    active_profile = None

    if username:
        # Retrieve the pre-computed profile from the DB to skip external API calls
        active_profile = TalentProfile.objects.filter(username__iexact=username).first()

    # 2. Fetch the 3 most recent profiles for the quick-access chips below the search bar
    featured_profiles = TalentProfile.objects.all().order_by("-updated_at")[:3]

    return render(
        request,
        "core/index.html",
        {
            "active_profile": active_profile,
            "featured_profiles": featured_profiles,
        },
    )


def audit_user_view(request):
    """
    Processes the audit search form submission.
    
    Workflow:
    1. Validates POST method and sanitizes username/URL input.
    2. Enforces IP-based rate limiting (max 5 new evaluations/min).
    3. Checks the 24-hour database cache to eliminate duplicate external API calls.
    4. Fetches GitHub repository data and triggers the Gemini evaluation pipeline.
    5. Saves/updates the candidate record in the DB and renders the result in-place.
    """
    # Guard against accidental GET requests to the submission endpoint
    if request.method != "POST":
        return redirect("core:index")

    # 1. Input Sanitization: Strip URLs, protocols, slashes, or '@' symbols
    # Handles inputs like 'https://github.com/Ezra-Men', '@Ezra-Men', or 'Ezra-Men'
    raw_input = request.POST.get("username", "").strip()
    username = raw_input.rstrip("/").split("/")[-1].lstrip("@").strip()

    # Fetch featured chips for template re-rendering in case of errors
    featured_profiles = TalentProfile.objects.all().order_by("-updated_at")[:3]

    if not username:
        return render(
            request,
            "core/index.html",
            {
                "error": "Please enter a valid GitHub username or profile link.",
                "featured_profiles": featured_profiles,
            },
        )

    # 2. IP Throttling: Restrict each client IP to 5 fresh evaluations per minute
    ip_address = request.META.get("REMOTE_ADDR", "unknown")
    rate_limit_key = f"audit_rate_{ip_address}"
    audit_count = cache.get(rate_limit_key, 0)

    if audit_count >= 5:
        return render(
            request,
            "core/index.html",
            {
                "error": "Rate limit exceeded. Please wait a minute before analyzing another profile.",
                "featured_profiles": featured_profiles,
            },
        )

    # 3. Database Cache Check: Serve existing data if audited within the last 24 hours
    one_day_ago = timezone.now() - timedelta(hours=24)
    existing_profile = TalentProfile.objects.filter(
        username__iexact=username,
        updated_at__gte=one_day_ago,
    ).first()

    if existing_profile:
        # Return cached profile instantly without burning GitHub or Gemini API quotas
        return render(
            request,
            "core/index.html",
            {
                "active_profile": existing_profile,
                "featured_profiles": featured_profiles,
            },
        )

    # 4. Ingestion & AI Evaluation Pipeline
    try:
        # Step A: Ingest public repos, commits, and language stats from GitHub REST API
        gh_service = GitHubService()
        gh_data = gh_service.fetch_user_data(username)

        # Step B: Run multi-tier evaluation through Gemini with retry and fallback logic
        ai_service = AIService()
        evaluation = ai_service.evaluate_developer(gh_data)

        # Step C: Upsert candidate profile record in the database
        profile, _ = TalentProfile.objects.update_or_create(
            username=gh_data["profile"]["username"],
            defaults={
                "name": gh_data["profile"]["name"] or username,
                "avatar_url": gh_data["profile"]["avatar_url"],
                "bio": gh_data["profile"]["bio"],
                "location": gh_data["profile"]["location"],
                "public_repos_count": gh_data["profile"]["public_repos_count"],
                "followers_count": gh_data["profile"]["followers_count"],
                "primary_role": evaluation.primary_role,
                "seniority_level": evaluation.seniority_level,
                "confidence_score": evaluation.confidence_score,
                "top_skills": evaluation.top_skills,
                "metrics_signals": evaluation.metrics_signals.model_dump(),
                "summary": evaluation.summary,
            },
        )

        # Increment throttle counter with a 60-second window
        cache.set(rate_limit_key, audit_count + 1, timeout=60)

        # Render the audit passport card directly on the single-scroll page
        return render(
            request,
            "core/index.html",
            {
                "active_profile": profile,
                "featured_profiles": featured_profiles,
            },
        )

    except (GitHubServiceError, AIServiceError) as err:
        # Gracefully handle API failures (e.g., user not found, rate limits, surges)
        return render(
            request,
            "core/index.html",
            {
                "error": str(err),
                "featured_profiles": featured_profiles,
            },
        )


def badge_view(request, username):
    """
    Generates a dynamic, Shields.io-style SVG verification badge.
    
    Can be embedded directly into candidate GitHub READMEs:
    [![DevAudit Verified](https://domain.com/badge/Ezra-Men.svg)](https://domain.com/?user=Ezra-Men)
    """
    clean_username = username.strip().lstrip("@")
    profile = TalentProfile.objects.filter(username__iexact=clean_username).first()

    # Determine badge label and color depending on whether the candidate exists & their tier
    if profile:
        role = profile.primary_role
        tier = profile.get_seniority_level_display()
        badge_label = f"{role} • {tier}"
        status_color = (
            "#10b981"  # Emerald green for SENIOR
            if profile.seniority_level == "SENIOR"
            else ("#6366f1" if profile.seniority_level == "MID" else "#f59e0b")  # Indigo for MID, Amber for ENTRY
        )
    else:
        badge_label = "Candidate Not Audited"
        status_color = "#64748b"  # Slate grey fallback

    # Compute SVG canvas width based on text length to avoid text clipping
    text_length = len(badge_label)
    total_width = 110 + (text_length * 7)
    status_x = 100 + ((total_width - 100) / 2)

    # Render vector XML string directly
    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="24" viewBox="0 0 {total_width} 24">
      <linearGradient id="b" x2="0" y2="100%">
        <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
        <stop offset="1" stop-opacity=".1"/>
      </linearGradient>
      <clipPath id="a">
        <rect width="{total_width}" height="24" rx="4" fill="#fff"/>
      </clipPath>
      <g clip-path="url(#a)">
        <rect width="90" height="24" fill="#1f140e"/>
        <rect x="90" width="{total_width - 90}" height="24" fill="{status_color}"/>
        <rect width="{total_width}" height="24" fill="url(#b)"/>
      </g>
      <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
        <text x="45" y="16" fill="#fff" font-weight="bold">DevAudit</text>
        <text x="{status_x}" y="16" fill="#fff" font-weight="bold">{badge_label}</text>
      </g>
    </svg>"""

    return HttpResponse(svg_content, content_type="image/svg+xml")


def add_review_view(request, username):
    """
    Handles submission of peer vouches and recruiter endorsements.
    
    Supports both traditional POST redirection and HTMX partial swaps 
    for smooth, zero-reload community feedback updates.
    """
    if request.method != "POST":
        return redirect("core:index")

    profile = get_object_or_404(TalentProfile, username__iexact=username)

    reviewer_name = request.POST.get("reviewer_name", "").strip()
    reviewer_title = request.POST.get("reviewer_title", "").strip()
    rating = int(request.POST.get("rating", 5))
    comment = request.POST.get("comment", "").strip()

    if reviewer_name and comment:
        review = ProfileReview.objects.create(
            profile=profile,
            reviewer_name=reviewer_name,
            reviewer_title=reviewer_title or "Peer Collaborator",
            rating=min(max(rating, 1), 5),  # Clamp rating strictly between 1 and 5
            comment=comment,
        )

        # HTMX support: Return only the newly rendered review card for in-place DOM insertion
        if request.headers.get("HX-Request"):
            return render(request, "core/partials/review_item.html", {"review": review})

    return redirect(f"/?user={profile.username}#audit-result")