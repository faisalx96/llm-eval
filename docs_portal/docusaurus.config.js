// @ts-check

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'qym Developer Portal',
  tagline: 'Self-hosted docs for the qym SDK, CLI, and platform.',
  url: 'https://docs.qym.local',
  baseUrl: '/docs/',
  organizationName: 'qym',
  projectName: 'qym-docs',
  onBrokenLinks: 'throw',
  trailingSlash: true,
  future: {
    experimental_faster: {
      rspackBundler: true
    }
  },
  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn'
    }
  },
  presets: [
    [
      'classic',
      {
        docs: {
          routeBasePath: '/',
          sidebarPath: require.resolve('./sidebars.js')
        },
        blog: false,
        pages: false,
        theme: {
          customCss: require.resolve('./src/css/custom.css')
        }
      }
    ]
  ],
  themes: [
    [
      require.resolve('@easyops-cn/docusaurus-search-local'),
      {
        hashed: true,
        language: ['en'],
        docsRouteBasePath: '/',
        indexDocs: true,
        indexBlog: false,
        indexPages: false
      }
    ]
  ],
  themeConfig: {
    navbar: {
      title: 'qym Docs',
      items: [
        {to: '/', label: 'Docs', position: 'left'},
        {type: 'search', position: 'right'}
      ]
    },
    colorMode: {
      defaultMode: 'light',
      disableSwitch: true
    }
  }
};

module.exports = config;
