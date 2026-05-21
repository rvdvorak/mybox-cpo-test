# Frontend image. Build context is ./frontend (see docker-compose.yml).
#
# Node 22 LTS: Vite 8 requires Node 20.19+ / 22.12+. alpine is fine here —
# the frontend has no native deps that need a C toolchain.
FROM node:22-alpine

WORKDIR /app

# Install deps first so the layer is cached when only source changes.
COPY package.json ./
RUN npm install

COPY . .

# Vite dev server (architektura 8 — no production build / nginx for MVP).
# VITE_API_URL is read from the container environment at runtime.
EXPOSE 8080

CMD ["npm", "run", "dev"]
