// @ts-check

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'qym Docs',
  tagline: 'Docs for qym app users, SDK developers, platform operators, and contributors.',
  url: 'https://docs.qym.local',
  baseUrl: '/docs/',
  favicon: 'img/qym_icon.png',
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
