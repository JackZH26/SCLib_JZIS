# syntax=docker/dockerfile:1.7
# Build from the repository root; both first-party packages are explicit inputs.
FROM python:3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e
COPY --from=ghcr.io/astral-sh/uv@sha256:440fd6477af86a2f1b38080c539f1672cd22acb1b1a47e321dba5158ab08864d /uv /bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=0 TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache PATH="/opt/venv/bin:$PATH"
# CVE-2026-109518: upgrade APT without its vulnerable download-retry path.
RUN apt-get -o Acquire::Retries=0 update && apt-get -o Acquire::Retries=0 install -y --no-install-recommends \
        apt libapt-pkg7.0 zlib1g build-essential libpq-dev libpcre2-8-0 tini \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' apt)" ge '3.0.4' \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' libapt-pkg7.0)" ge '3.0.4' \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' zlib1g)" ge '1:1.3.dfsg+really1.3.1-1+deb13u1' \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' libpcre2-8-0)" ge '10.46-1~deb13u3' \
    && rm -rf /var/lib/apt/lists/*
COPY api /opt/packages/api
COPY ingestion /opt/packages/ingestion
COPY publisher /opt/packages/publisher
WORKDIR /opt/packages/publisher
RUN uv sync --frozen --no-dev --no-editable \
    && python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" \
    && rm -rf /root/.cache/uv /opt/packages \
      /usr/local/lib/python3.11/site-packages/pip* /usr/local/lib/python3.11/site-packages/setuptools* \
      /usr/local/lib/python3.11/site-packages/wheel* \
    && rm -f /usr/local/bin/pip* /bin/uv
COPY publisher/uv.lock publisher/pyproject.toml /app/
WORKDIR /tmp
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA
RUN groupadd --system --gid 1001 sclib \
    && useradd --system --uid 1001 --gid sclib --home /tmp sclib
USER 1001:1001
RUN --network=none python -I -c "from services.schema_lifecycle import expected_heads; assert expected_heads()==('0117_retrieval_policy_v4',); import tiktoken; tiktoken.get_encoding('cl100k_base')"
ENTRYPOINT ["/usr/bin/tini", "--", "sclib-publish-native"]
CMD ["--help"]
