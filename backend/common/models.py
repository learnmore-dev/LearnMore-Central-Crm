from django.db import models


class IdentifierSequence(models.Model):
    """Locked counters, independent of record counts or deletions."""
    name = models.CharField(max_length=20, primary_key=True)
    value = models.PositiveBigIntegerField(default=0)
