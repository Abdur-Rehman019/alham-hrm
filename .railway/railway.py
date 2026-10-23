from railway_sdk import define_railway, github, project, service
# This repository manages only its own resources in the environment. Other
# repositories export their own partial name.
# See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
PARTIAL = "web"
@define_railway
def main(ctx=None):
    web = service(
        "web",
        source=github("Abdur-Rehman019/alham-hrm", **{ "branch": "main", "checkSuites": False }),
        build={ "buildEnvironment": "V3", "builder": "RAILPACK" },
        # Same command as the Procfile; keep the two in step.
        start=(
            "python manage.py migrate --noinput && python manage.py collectstatic --noinput && "
            "gunicorn alham_hrm.wsgi --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} "
            "--timeout 60 --access-logfile - --error-logfile -"
        ),
        healthcheck="/healthz/",
        healthcheckTimeout=120,
        replicas={ "sfo": 1 },
    )
    return project("outstanding-mercy", variables={"managed": False}, resources=[web])
