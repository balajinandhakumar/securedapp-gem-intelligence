# SecuredApp frontend — production Dockerfile
# Builds the React app locally (npm run build) and copies the dist folder
# into an nginx image for serving.
#
# The frontend is built on the host machine (Windows/Linux/macOS) and the
# resulting dist/ directory is copied into the Docker image. Vite produces
# platform-independent static assets (HTML/JS/CSS), so a Windows build works
# perfectly when served by nginx on Linux.

FROM nginx:1.27-alpine AS runtime

# Copy pre-built frontend assets
COPY dist /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port 80
EXPOSE 80

# Health check for the frontend service
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:80/health || exit 1

CMD ["nginx", "-g", "daemon off;"]