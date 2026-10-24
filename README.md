# ALHAM HRM

ALHAM HRM is the staff, attendance, enrollment, and payroll system for ALHAM Overseas Consultants. It is a Django application deployed to Railway, using SQLite for local development and PostgreSQL when `DATABASE_URL` is configured.

## Requirements

- Python 3.13 (the project is tested with Django 6.x)
- Git
- An SMTP account if you want payslips delivered by email; the default local console backend does not deliver mail

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

To test actual payslip delivery locally, also configure your SMTP provider in `.env`:

```dotenv
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-smtp-username
EMAIL_HOST_PASSWORD=your-smtp-password
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=ALHAM HRM <verified-sender@example.com>
```

Use the provider's SMTP credentials (for Gmail, an app password with 2-Step Verification enabled), not an ordinary mailbox password. Never commit these values or share them in chat. Without SMTP configuration, the app now records a failed email attempt and tells the administrator that the console backend cannot deliver the payslip. An SMTP server accepting the message does not guarantee inbox delivery; check the recipient address, spam folder, and provider delivery logs.

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

If you explicitly need sample records in a Railway PostgreSQL environment, deploy this code first, back up the database, then run a one-time command inside the web service using the Railway CLI:

```powershell
railway ssh --service <web-service-name> -- python manage.py seed_demo_data --months 6 --allow-production
```

Production seeding requires `DEBUG=False` and PostgreSQL, is wrapped in one transaction, creates no demo logins, and does not create or modify shared incentive rules. It adds only the clearly named demo employees and their synthetic attendance, enrollments, and unapproved payroll rows. These rows appear in live reports, so use a separate staging database instead if production reports must contain only real business data. The command is idempotent and safe to rerun for the same date range.

## Configuration

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Required Django secret; keep it in the host's secret store. |
| `DEBUG` | `False` in production. |
| `ALLOWED_HOSTS` | Comma-separated host names. |
| `DATABASE_URL` | Optional database URL; omit locally to use SQLite. |
| `BREVO_API_KEY` | Recommended on Railway. Sends email through Brevo's HTTPS API, which works on every Railway plan. |
| `EMAIL_BACKEND` | Optional. Chosen automatically: Brevo when `BREVO_API_KEY` is set, SMTP when `EMAIL_HOST` is set, otherwise console (prints only, delivers nothing). |
| `EMAIL_HOST` | SMTP server hostname (only if SMTP is allowed on your Railway plan). |
| `EMAIL_PORT` | SMTP port, commonly `587` with TLS. |
| `EMAIL_HOST_USER` | SMTP account name. |
| `EMAIL_HOST_PASSWORD` | SMTP credential or provider app password. |
| `EMAIL_USE_TLS` | `True` for STARTTLS on port 587. |
| `EMAIL_TIMEOUT` | SMTP connection timeout in seconds; defaults to 10. |
| `DEFAULT_FROM_EMAIL` | Sender shown on payslip messages. |
| `SECURE_SSL_REDIRECT` | Defaults to `True` when `DEBUG=False`; set only when the deployment proxy configuration requires it. |
| `MEDIA_ROOT` | Where uploaded employee photos are stored. On Railway, point it at a mounted volume (e.g. `/data/media`). |

### Setting up email (password reset links and payslips)

Railway blocks outgoing SMTP on its Free, Trial and Hobby plans, so use Brevo's HTTPS API:

1. Create a free account at brevo.com. Under **Senders, Domains & Dedicated IPs**, add and verify the sender address you will send from (a Gmail address works).
2. Under **SMTP & API → API Keys**, create an API key.
3. In Railway, open the `web` service → **Variables** and add `BREVO_API_KEY` (the key) and `DEFAULT_FROM_EMAIL`, e.g. `ALHAM HRM <your-verified-sender@gmail.com>`. Railway redeploys automatically.
4. Check delivery from your computer: `railway run --service web python manage.py send_test_email you@example.com`, or use **Forgot your password?** on the login page.

Until email is configured, the deploy log shows warning `core.W001`, the reset page tells people to ask HR, and payslip approval says the payslip was not sent and why. A password reset link goes to the login's email, or to the email on the employee's HR record when the login has none.

Keep secrets in Railway Variables, not in source control. An administrator must approve each generated payroll row; approval immediately attempts to send that employee's payslip, with a text breakdown and PDF attachment. An approved payroll can be resent by an administrator if delivery fails or a resend is needed. Changing payroll amounts during regeneration clears approval and requires a fresh approval. Payslips go to `Employee.email` (the HR record); the login's own email is only the fallback. Changing an employee's email also updates their login's email. Placeholder addresses such as the demo data's `@example.invalid` are refused with a clear message instead of being "sent" to an inbox that does not exist. Every attempt, including skipped or failed sends, is retained in the payroll email audit table.

## Security features

- **Two-factor sign-in for admins.** Every staff/superuser sign-in also needs a 6-digit code from an authenticator app (Google or Microsoft Authenticator). The first sign-in shows a QR code to set it up and 10 one-time backup codes. Employees are not affected. Ticking **Remember this computer** skips the code on that browser for 30 days; it is forgotten when the admin signs out on that computer, changes their password, has two-factor reset, or clicks **Forget all remembered computers** on the Two-factor security page (only a hash of the cookie is stored). Settings: **Two-factor security** in the sidebar (new backup codes). Lost phone: sign in with a backup code; or a superuser deletes the person's device under **Django Admin → TOTP devices**; or, if the only superuser is locked out, run `python manage.py reset_two_factor <username>` on the server (`railway ssh --service web` after adding an SSH key with `ssh-keygen`). `ADMIN_2FA_REQUIRED=False` switches it off (not recommended).
- **Audit log.** Sidebar → **Audit Log** lists every create/change/delete of employees (including salary), payroll (including approvals and payslip emails), incentive rules, enrollments and login accounts, with who, when, IP address, and old → new values. Passwords are logged only as "changed". Entries cannot be edited or deleted in the app or Django Admin.

## Business rules

- Self check-in must come from the office. HR sets this up under **Check-in Location** (while at the office): the office internet IP ("add it" button) and/or the office GPS point and radius (default 150 m). A check-in from office Wi-Fi **or** inside the radius counts as present; anything else, including refused location access, is still recorded but goes to **Attendance Review** with the distance, IP and a map link. "Require both" makes it stricter (needs a static IP). Until the page is set up, check-ins are accepted from anywhere. GPS can be faked with special apps; for stronger proof use the office IP, a biometric device (import), or review repeated off-site check-ins.
- Office hours are 10:00–18:00 (`OFFICE_START`, `OFFICE_END`). A check-in up to 10:15 is on time, from 10:16 it is marked late (`LATE_GRACE_MINUTES`, default 15). Employees can check themselves in only between 08:00 (`CHECK_IN_OPENS`) and 18:00, so a check-in at midnight is refused.
- HR corrects any day (wrong check-in time, wrong status, a forgotten check-in) with **Edit** in the attendance log on the employee's page. A reason is required; it is saved on the record and in the Audit Log with the old and new values. Changing a day to or from Leave keeps the leave records and free-leave allowance in step; if payroll for that month already exists, HR is reminded to regenerate it.
- Sunday is the weekly holiday; attendance expects Monday through Saturday.
- Approved leave beyond the monthly allowance is deducted using monthly salary divided by the calendar days in that month.
- Unexplained absent working days are also deducted at the same calendar-day rate. Today is not counted as absent until the day ends.
- Salary is not prorated in join or leave months; the full monthly base is used.
- Salary, deductions, incentives, and net pay are rounded half-up to whole PKR rupees; decimals are not accepted or displayed.
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
4. `.railway/railway.py` (Railway Infrastructure as Code) sets the health check on `/healthz/`, so a broken build is never switched live, and the start command. Railway does not read this file on deploy: after changing it, run `railway config plan` to preview and `railway config apply` to save it to Railway. The CLI evaluates it with `python3`, so first `pip install -r .railway/requirements.txt` into `.venv`, copy `.venv\Scripts\python.exe` to `python3.exe`, and put `.venv\Scripts` first on `PATH`. Keep its start command identical to the Procfile. The Procfile runs database migrations and `collectstatic` before Gunicorn, binding to Railway's injected `PORT` on `0.0.0.0` (with port 8000 as a local fallback). Review deployment logs for migration, static-collection, and startup failures; never run `makemigrations` as part of production startup.
5. Log in with the existing superuser, confirm an employee can log in and is forced to change a temporary password, generate a payroll, then approve it to test automatic payslip delivery to a controlled address.
6. Verify `DEBUG=False`, HTTPS redirects/cookies, static assets, database persistence after redeploy, and a recovery-tested backup.

Do not place credentials in GitHub, the Procfile, or this README. Use Railway's secret variables. Production's SQLite fallback is not suitable for persistent hosting; use PostgreSQL.

## Backups and files

Back up the Railway PostgreSQL database on a schedule using Railway's supported backups or a separately secured `pg_dump` process. Store backups outside the application service, restrict access, retain multiple recovery points, and periodically test restoring one. Confirm backup scope and retention with the system owner before making changes to production data.

Employee photos live under `MEDIA_ROOT` and are served only to signed-in users. Railway's disk is wiped on every deploy, so add a Volume to the `web` service (mount path e.g. `/data`) and set `MEDIA_ROOT=/data/media`, or photos will disappear. The system does not automatically email payslips on a schedule; an administrator approves each payroll row, which sends that employee's payslip.

## Manual UAT

Use the `UAT_ALHAM_HRM.xlsx` workbook as the execution record. Before testing, use a non-production database and controlled email addresses. For local graph and portal checks, use `python manage.py seed_demo_data --months 6 --create-logins`; otherwise create an administrator and sample employees, configure country incentive rules, and prepare test enrollments, attendance, and payroll rows.

For each workbook row, follow the prerequisites and steps, compare actual behavior to the expected result, then record the tester, date, Pass/Fail result, and evidence or notes. Run the production-readiness cases only against an approved staging deployment. Do not use live employee personal data in test records. Re-test failed cases after a fix, and verify a database restore independently of a normal redeploy.
