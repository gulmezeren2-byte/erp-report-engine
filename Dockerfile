# erp-report-engine — a small image that runs the CLI.
#
#   docker build -t erp-report-engine .
#   docker run --rm -v "$PWD:/work" erp-report-engine init-demo
#   docker run --rm -v "$PWD:/work" erp-report-engine run -c config.demo.yaml
#   docker run --rm -e ERP_DB_URL -v "$PWD:/work" erp-report-engine run -c config.yaml
#
# SQLite and PostgreSQL work out of the box. For MSSQL (Logo/Netsis/Mikro), add
# Microsoft's ODBC driver (msodbcsql18) to this image and install the [mssql]
# extra — see the README "Install" section.
#
# Pinned by digest so the same commit always builds the same base, not whatever
# python:3.12-slim happens to point at that day. The tag is kept alongside for
# readability; Dependabot bumps both together (see .github/dependabot.yml).
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY erp_report_engine ./erp_report_engine
RUN pip install --no-cache-dir ".[postgres]"

# never run as root; work out of a mounted /work volume
RUN useradd --create-home --uid 10001 app
USER app
WORKDIR /work

ENTRYPOINT ["erp-report-engine"]
CMD ["--help"]
