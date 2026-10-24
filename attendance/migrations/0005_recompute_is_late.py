from django.db import migrations


def recompute_is_late(apps, schema_editor):
    """Lateness used to be set only by demo data; apply the office-hours rule to every record."""
    from attendance.models import is_late_check_in
    DailyAttendance = apps.get_model('attendance', 'DailyAttendance')
    late_ids, on_time_ids = [], []
    for pk, status, check_in in DailyAttendance.objects.values_list('pk', 'status', 'check_in_time').iterator():
        (late_ids if status == 'present' and is_late_check_in(check_in) else on_time_ids).append(pk)
    DailyAttendance.objects.filter(pk__in=late_ids).update(is_late=True)
    DailyAttendance.objects.filter(pk__in=on_time_ids).update(is_late=False)


class Migration(migrations.Migration):
    dependencies = [('attendance', '0004_leaverequest')]

    operations = [migrations.RunPython(recompute_is_late, migrations.RunPython.noop)]
