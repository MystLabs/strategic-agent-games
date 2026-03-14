FROM node:20-slim AS dashboard-build
WORKDIR /app/dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY . .
COPY --from=dashboard-build /app/dashboard/dist ./dashboard/dist

ENV PORT=8888
EXPOSE 8888
CMD ["python", "run_arena.py", "--no-browser", "--host", "0.0.0.0"]
