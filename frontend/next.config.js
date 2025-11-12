/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    domains: ['images.unsplash.com'],
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  },
  // Rewrites only for local Docker development
  // Disabled in production - use NEXT_PUBLIC_API_URL env var instead
  async rewrites() {
    // Only enable rewrites if running in Docker (when NEXT_PUBLIC_API_URL is not set)
    if (!process.env.NEXT_PUBLIC_API_URL) {
      return [
        {
          source: '/api/:path*',
          destination: 'http://backend:8000/api/:path*',
        },
      ];
    }
    return [];
  },
}

module.exports = nextConfig 