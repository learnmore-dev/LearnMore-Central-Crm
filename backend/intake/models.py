import uuid
from django.conf import settings
from django.db import models


class WebsiteSource(models.Model):
    SITES = [('learnmoretech', 'learnmoretech.in'), ('learnmoretechnologies', 'learnmoretechnologies.in')]
    slug = models.CharField(max_length=40, choices=SITES, unique=True)
    default_branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, related_name='website_sources')
    allowed_branches = models.ManyToManyField('branches.Branch', related_name='allowed_website_sources')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)

    @property
    def domain(self):
        return dict(self.SITES)[self.slug]


class WebsiteSubmission(models.Model):
    class Status(models.TextChoices):
        CREATED = 'created', 'Enquiry created'
        REVIEW = 'review', 'Identity review required'
        REJECTED = 'rejected', 'Rejected after review'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(WebsiteSource, on_delete=models.PROTECT)
    submission_id = models.CharField(max_length=100)
    request_hash = models.CharField(max_length=64)
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT)
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    course = models.CharField(max_length=180, blank=True)
    message = models.TextField(max_length=2000, blank=True)
    page_url = models.URLField(max_length=1000, blank=True)
    form_name = models.CharField(max_length=100, blank=True)
    preferred_branch = models.CharField(max_length=100, blank=True)
    training_mode = models.CharField(max_length=50, blank=True)
    utm = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status.choices)
    lead = models.OneToOneField('leads.Lead', null=True, on_delete=models.PROTECT, related_name='website_submission')
    review = models.OneToOneField('contacts.DuplicateReview', null=True, on_delete=models.PROTECT, related_name='website_submission')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [models.UniqueConstraint(fields=['source', 'submission_id'], name='unique_website_submission')]
