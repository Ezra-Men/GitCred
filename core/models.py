from django.db import models

# Create your models here.
from django.db import models

# Create your models here.
from django.db import models


class SeniorityLevel(models.TextChoices):
  ENTRY = 'ENTRY', 'Entry Level'
  MID = 'MID', 'Mid Level'
  SENIOR = 'SENIOR', 'Senior Level'


class TalentProfile(models.Model):
  # Candidate Public GitHub Identity
  username = models.CharField(max_length=100, unique=True, db_index=True)
  name = models.CharField(max_length=150, blank=True, null=True)
  avatar_url = models.URLField(max_length=500, blank=True, null=True)
  bio = models.TextField(blank=True, null=True)
  location = models.CharField(max_length=150, blank=True, null=True)
  public_repos_count = models.PositiveIntegerField(default=0)
  followers_count = models.PositiveIntegerField(default=0)

  # AI / Algorithmic Evaluation Verdict
  primary_role = models.CharField(
      max_length=100,
      help_text=(  # e.g., 'DevOps Engineer', 'Backend Engineer'
          'Primary engineering domain'
      ),
  )
  seniority_level = models.CharField(
      max_length=20,
      choices=SeniorityLevel.choices,
      default=SeniorityLevel.ENTRY,
  )
  confidence_score = models.PositiveIntegerField(
      default=0, help_text='Evaluation confidence score between 0 and 100'
  )

  # Structured Breakdown
  # e.g. ["Python", "Docker", "PostgreSQL", "FastAPI"]
  top_skills = models.JSONField(default=list, blank=True)

  # e.g. {"commit_cadence": "High", "test_coverage": "Moderate", "dominant_language": "Go"}
  metrics_signals = models.JSONField(default=dict, blank=True)

  # 2-3 sentence AI assessment summary
  summary = models.TextField(blank=True, null=True)

  # Cache / Invalidation timestamp
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    ordering = ['-updated_at']
    verbose_name = 'Talent Profile'
    verbose_name_plural = 'Talent Profiles'

  def __str__(self):
    return (
        f'{self.username} - {self.primary_role} ({self.get_seniority_level_display()})'
    )


class ProfileReview(models.Model):
  profile = models.ForeignKey(
      TalentProfile, on_delete=models.CASCADE, related_name="reviews"
  )
  reviewer_name = models.CharField(max_length=120)
  reviewer_title = models.CharField(
      max_length=150,
      help_text="e.g. Senior Tech Lead, Recruiter at Acme, Peer Contributor",
  )
  rating = models.PositiveSmallIntegerField(
      default=5,
      choices=[(i, f"{i} Stars") for i in range(1, 6)],
  )
  comment = models.TextField(max_length=1000)
  created_at = models.DateTimeField(auto_now_add=True)

  class Meta:
    ordering = ["-created_at"]

  def __str__(self):
    return f"Review by {self.reviewer_name} for {self.profile.username}"