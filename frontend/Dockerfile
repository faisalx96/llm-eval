# Multi-stage build for LLM-Eval Frontend (Next.js)
# Production-optimized Docker image with security best practices

# Base stage for shared dependencies
FROM node:20-alpine as base

# Set build arguments
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION=0.3.0

# Add metadata labels
LABEL maintainer="faisalx96@yahoo.com"
LABEL org.opencontainers.image.title="LLM-Eval Frontend"
LABEL org.opencontainers.image.description="UI-first LLM evaluation platform frontend"
LABEL org.opencontainers.image.version=$VERSION
LABEL org.opencontainers.image.created=$BUILD_DATE
LABEL org.opencontainers.image.revision=$VCS_REF

# Install system dependencies
RUN apk add --no-cache libc6-compat curl

# Set work directory
WORKDIR /app

# Create non-root user
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Dependencies stage - install and cache dependencies
FROM base as deps

# Copy package files
COPY package.json package-lock.json* ./

# Install dependencies
RUN npm ci --only=production --frozen-lockfile

# Builder stage - build the application
FROM base as builder

WORKDIR /app

# Copy dependencies from deps stage
COPY --from=deps /app/node_modules ./node_modules

# Copy source code
COPY . .

# Build arguments for environment variables
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NODE_ENV=production

# Set environment variables
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NODE_ENV=$NODE_ENV
ENV NEXT_TELEMETRY_DISABLED=1

# Build the application
RUN npm run build

# Production stage - minimal runtime image
FROM base as production

WORKDIR /app

# Set environment variables
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Create nextjs user
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Copy built application
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# Create cache directory
RUN mkdir -p .next/cache && chown nextjs:nodejs .next/cache

# Switch to non-root user
USER nextjs

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:3000/api/health || exit 1

# Start the application
CMD ["node", "server.js"]