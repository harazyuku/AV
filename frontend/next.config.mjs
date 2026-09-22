/** @type {import('next').NextConfig} */
const nextConfig = {
  async redirects() {
    return [
      {
        source: '/imports',
        destination: '/admin/imports',
        permanent: false,
      },
      {
        source: '/videos',
        destination: '/admin/videos',
        permanent: false,
      },
      {
        source: '/manual-import',
        destination: '/admin/manual-import',
        permanent: false,
      },
    ]
  },
}

export default nextConfig
