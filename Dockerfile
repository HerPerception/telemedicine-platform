# The telemedicine application.
#
# One image, two jobs: the API (`scripts/run_server.py`) and the delivery
# worker (`scripts/run_delivery.py`). Which one a container runs is decided by
# its command, so the two always have the same code and the same settings.
#
# The image has no compiler tools and no tests in it. It runs as a user that
# is not root, and it holds one thing: the application and the one dependency
# it needs, the PostgreSQL driver.

FROM python:3.12-slim

# Fail the build rather than send a message that says nothing.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The package and its one dependency are installed first, so that a change
# to the code does not reinstall them.
COPY pyproject.toml README.md LICENSE ./
COPY telemedicine ./telemedicine
RUN pip install --no-cache-dir .

# The entry points, the schema and the documentation.
COPY scripts ./scripts
COPY db ./db
COPY docs ./docs

# The audit anchors are published here, outside the database. A volume keeps
# them across restarts; a deployment that wants them to be worth something
# copies them somewhere the application cannot write.
RUN mkdir -p /var/lib/telemedicine \
    && useradd --system --create-home --uid 10001 --home-dir /home/telemedicine telemedicine \
    && chown -R telemedicine:telemedicine /app /var/lib/telemedicine
USER telemedicine

ENV TELEMEDICINE_HOST=0.0.0.0 \
    TELEMEDICINE_PORT=8080

EXPOSE 8080

# The check asks the server whether it is serving, and the database whether it
# is there and whether the schema has been applied.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python3", "scripts/healthcheck.py"]

CMD ["python3", "scripts/run_server.py"]
