# Backend image. Build context is ./backend (see docker-compose.yml),
# so all paths below are relative to the backend/ directory.
#
# Full python:3.14 (not -slim): asyncpg has no prebuilt wheel for Python 3.14
# yet, so pip compiles it from source — which needs the C toolchain + libc
# headers bundled in the full image but stripped from -slim.
FROM python:3.14

WORKDIR /app

# pyproject.toml sits above the package directory; setuptools
# (packages=["backend", ...]) then resolves the sources copied into
# /app/backend/ below.
COPY pyproject.toml /app/pyproject.toml
COPY . /app/backend/

# Installs FastAPI / SQLAlchemy / asyncpg / uvicorn / pydantic from pyproject.toml.
RUN pip install --no-cache-dir /app

EXPOSE 3000

# Runs backend/__main__.py as a package so relative imports resolve.
ENTRYPOINT ["python", "-m", "backend"]
