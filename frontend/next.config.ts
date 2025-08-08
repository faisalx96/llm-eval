import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
  experimental: {
    outputFileTracingRoot: '../',
  },
  // Environment variable configuration
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  },
  // Image optimization for production
  images: {
    unoptimized: true, // For better Docker compatibility
  },
  // Disable telemetry in production
  telemetry: false,
};
