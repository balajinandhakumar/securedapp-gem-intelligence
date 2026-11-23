# SecuredApp frontend — production Dockerfile (multi-stage)
#
# Stage 1: Build the React/Vite application with Node.
# Stage 2: Serve the generated static assets with nginx.
#
# No locally pre-generated frontend/dist directory is required: the build
# happens inside Docker using the committed lockfile.

# ---------------------------------------------------------------
# Stage 1: Build
# ---------------------------------------------------------------
FROM node:24-alpine AS builder

WORKDIR /app

# Install dependencies from the committed lockfile (reproducible builds).
# Dev dependencies are retained because `npm run build` runs `tsc` and
# `vite build`, which need TypeScript, Vite, and the testing toolchain.
COPY package.json package-lock.json ./
RUN npm ci

# Copy source code and build static assets into /app/dist.
COPY . .
RUN npm run build

# ---------------------------------------------------------------
# Stage 2: Runtime (nginx)
# ---------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

# wget is required by the HEALTHCHECK (and by docker-compose's frontend probe).
# The nginx:alpine image does not ship wget by default, so install it here.
RUN apk add --no-cache wget ca-certificates

# Copy built frontend assets from the build stage.
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port 80
EXPOSE 80

# Health check for the frontend service
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:80/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
