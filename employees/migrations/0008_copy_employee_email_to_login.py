from django.db import migrations


def copy_email_to_login(apps, schema_editor):
    """Logins created without an email could never use "Forgot password"; give them the HR email."""
    Employee = apps.get_model('employees', 'Employee')
    User = apps.get_model('auth', 'User')
    for employee in Employee.objects.exclude(user=None).exclude(email=None).exclude(email=''):
        User.objects.filter(pk=employee.user_id, email='').update(email=employee.email)


class Migration(migrations.Migration):
    dependencies = [
        ('employees', '0007_alter_employee_monthly_salary'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(copy_email_to_login, migrations.RunPython.noop),
    ]
