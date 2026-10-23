from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import IncentiveRule, StudentEnrollment


@receiver(post_save, sender=IncentiveRule)
def backfill_unpaid_enrollments(sender, instance, **kwargs):
    StudentEnrollment.objects.filter(
        destination_country__iexact=instance.destination_country,
        incentive_amount=0,
        incentive_paid=False,
    ).update(incentive_amount=instance.amount)
