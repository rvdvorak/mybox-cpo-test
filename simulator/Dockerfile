# Station simulator image. Build context is ./simulator (see docker-compose.yml),
# so all paths below are relative to the simulator/ directory.
FROM python:3.14-slim

WORKDIR /app

# pyproject.toml sits above the package directory; setuptools (packages=["simulator"])
# then resolves the sources copied into /app/simulator/ below.
COPY pyproject.toml /app/pyproject.toml
COPY . /app/simulator/

# Installs aiomqtt — the single declared dependency — from pyproject.toml.
RUN pip install --no-cache-dir /app

# Runs simulator/__main__.py as a package so relative imports resolve.
ENTRYPOINT ["python", "-m", "simulator"]
