# ALHAM HRM

ALHAM HRM is the staff, attendance, enrollment, and payroll system for ALHAM Overseas Consultants. It is a Django application deployed to Railway, using SQLite for local development and PostgreSQL when `DATABASE_URL` is configured.

## Requirements

- Python 3.13 (the project is tested with Django 6.x)
- Git
- A local SMTP test account only if you want to test real delivery; the default local email backend prints messages to the console

## Local setup

From the project root, create and activate a virtual environment, then install the pinned project requirements:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create a local `.env` file (never commit it) with a unique secret key:

```dotenv
SECRET_KEY=replace-with-a-long-random-secret
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
```

For example, generate a secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and paste the result into `.env`. The local database defaults to `db.sqlite3`. Prepare the database and run the development server:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. Staff sign in at `/accounts/login/`; the superuser manages employees, attendance, enrollments, and payroll. Use the Django admin only for supported administrative maintenance.

To populate a local database with six demo employees and six months of attendance, leave, enrollment, incentive, and payroll data, run:

```powershell
python manage.py seed_demo_data --months 6 --create-logins
```

This command refuses to run unless `DEBUG=True` and the database is SQLite. It creates demo-only employee profiles and never seeds existing employees. It prints random temporary passwords for the demo portal accounts; change them at first sign-in. The demo email addresses use the reserved `.invalid` domain, so payslip emails cannot reach real recipients. Do not run demo data commands against production.

## Configuration

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Required Django secret; keep it in the host's secret store. |
| `DEBUG` | `False` in production. |
| `ALLOWED_HOSTS` | Comma-separated host names. |
| `DATABASE_URL` | Optional database URL; omit locally to use SQLite. |
| `EMAIL_BACKEND` | Optional Django backend. Defaults to console in local `DEBUG=True` and SMTP in production. |
| `EMAIL_HOST` | SMTP server hostname. |
| `EMAIL_PORT` | SMTP port, commonly `587` with TLS. |
| `EMAIL_HOST_USER` | SMTP account name. |
| `EMAIL_HOST_PASSWORD` | SMTP credential or provider app password. |
| `EMAIL_USE_TLS` | `True` for STARTTLS on port 587. |
| `EMAIL_TIMEOUT` | SMTP connection timeout in seconds; defaults to 10. |
| `DEFAULT_FROM_EMAIL` | Sender shown on payslip messages. |
| `SECURE_SSL_REDIRECT` | Defaults to `True` when `DEBUG=False`; set only when the deployment proxy configuration requires it. |

Set SMTP secrets in Railway Variables, not in source control. Production defaults to Django's SMTP backend; configure its host, port, account, password, TLS choice, and sender address before attempting delivery. An administrator must approve each generated payroll row; approval immediately attempts to send that employee's payslip, with a text breakdown and PDF attachment. An approved payroll can be resent by an administrator if delivery fails or a resend is needed. Changing payroll amounts during regeneration clears approval and requires a fresh approval. The linked login user's email is preferred; `Employee.email` is the fallback. Every attempt, including skipped or failed sends, is retained in the payroll email audit table.

Railway may restrict outbound SMTP on lower-tier plans. First verify Railway's current outbound mail limits and the chosen provider's port support. If SMTP cannot be used reliably, evaluate an HTTP mail API integration such as django-anymail with Brevo or Resend; do not add an email provider dependency until the SMTP path is confirmed unusable.

## Business rules

- Sunday is the weekly holiday; attendance expects Monday through Saturday.
- Approved leave beyond the monthly allowance is deducted using monthly salary divided by the calendar days in that month.
- Unexplained absent working days are also deducted at the same calendar-day rate. Today is not counted as absent until the day ends.
- Salary is not prorated in join or leave months; the full monthly base is used.
- Net pay is base salary minus leave and absence deductions plus incentives.
- Enrollment incentives are assigned from the destination-country rule and belong to the month of `confirmed_on`. Adding a missing rule backfills zero-valued, unpaid enrollments for that country; non-zero or already-paid amounts are preserved.
- Employees only see their own attendance, leave, enrollment, and salary data. They cannot download payslips or trigger payroll email.

## Tests and validation

Run the complete test suite and Django checks from the activated virtual environment:

```powershell
python manage.py test
python manage.py check
python manage.py makemigrations --check
```

The tests cover employee role isolation, portal rendering, payroll calculations, email sending with Django's in-memory mail backend, incentive backfill, and existing attendance, leave, and admin behavior. Test SMTP failures are mocked; successful real-world delivery must be checked in the target Railway/provider environment.

## Railway deployment

1. Connect the GitHub repository to a Railway project and provision a PostgreSQL database.
2. Add `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, and the SMTP environment variables to Railway Variables. Set `DATABASE_URL` to the provisioned PostgreSQL connection string if Railway has not injected it automatically.
3. Confirm the service's public domain is included in `ALLOWED_HOSTS`, and enable HTTPS.
4. The Procfile runs database migrations and `collectstatic` before Gunicorn, binding to Railway's injected `PORT` on `0.0.0.0` (with port 8000 as a local fallback). Review deployment logs for migration, static-collection, and startup failures; never run `makemigrations` as part of production startup.
5. Log in with the existing superuser, confirm an employee can log in and is forced to change a temporary password, generate a payroll, then approve it to test automatic payslip delivery to a controlled address.
6. Verify `DEBUG=False`, HTTPS redirects/cookies, static assets, database persistence after redeploy, and a recovery-tested backup.

Do not place credentials in GitHub, the Procfile, or this README. Use Railway's secret variables. Production's SQLite fallback is not suitable for persistent hosting; use PostgreSQL.

## Backups and files

Back up the Railway PostgreSQL database on a schedule using Railway's supported backups or a separately secured `pg_dump` process. Store backups outside the application service, restrict access, retain multiple recovery points, and periodically test restoring one. Confirm backup scope and retention with the system owner before making changes to production data.

Employee photos currently live under the service's local media directory and can be lost on Railway redeploys. Use S3-compatible object storage if photos must persist. The system does not automatically email payslips on a schedule; an administrator approves each payroll row, which sends that employee's payslip.

## Manual UAT

Use the `UAT_ALHAM_HRM.xlsx` workbook as the execution record. Before testing, use a non-production database and controlled email addresses. For local graph and portal checks, use `python manage.py seed_demo_data --months 6 --create-logins`; otherwise create an administrator and sample employees, configure country incentive rules, and prepare test enrollments, attendance, and payroll rows.

For each workbook row, follow the prerequisites and steps, compare actual behavior to the expected result, then record the tester, date, Pass/Fail result, and evidence or notes. Run the production-readiness cases only against an approved staging deployment. Do not use live employee personal data in test records. Re-test failed cases after a fix, and verify a database restore independently of a normal redeploy.
