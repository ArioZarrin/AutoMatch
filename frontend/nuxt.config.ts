export default defineNuxtConfig({
  ssr: false,
  devtools: { enabled: false },
  modules: ['vuetify-nuxt-module'],
  css: ['~/assets/styles/main.css'],
  vuetify: {
    moduleOptions: {
      importComposables: false,
      styles: {
        colors: false,
      },
    },
    vuetifyOptions: './vuetify.config.ts',
  },
  runtimeConfig: {
    public: {
      apiBase: '',
    },
  },
  nitro: {
    devProxy: {
      '/api': {
        target: 'http://127.0.0.1:8080/api',
        changeOrigin: true,
      },
    },
  },
  app: {
    head: {
      title: 'Vehicle Matcher',
      meta: [
        {
          name: 'description',
          content: 'Natural-language vehicle catalogue matcher',
        },
        {
          name: 'theme-color',
          content: '#050505',
        },
      ],
    },
  },
  typescript: {
    typeCheck: true,
  },
  compatibilityDate: '2026-07-26',
})
