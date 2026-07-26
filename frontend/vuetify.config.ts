import { defineVuetifyConfiguration } from 'vuetify-nuxt-module/custom-configuration'

export default defineVuetifyConfiguration({
  icons: {
    defaultSet: 'mdi-svg',
  },
  theme: {
    defaultTheme: 'vehicleDark',
    themes: {
      vehicleDark: {
        dark: true,
        colors: {
          background: '#050505',
          surface: '#111111',
          primary: '#788cff',
          secondary: '#72f8ff',
          success: '#47d18c',
          warning: '#ffe58f',
          error: '#ff6b78',
          info: '#76b8ff',
          'surface-variant': '#1c1c1f',
          'on-background': '#f4f4f5',
          'on-surface': '#f4f4f5',
          'on-primary': '#050505',
        },
      },
    },
  },
  defaults: {
    VBtn: {
      elevation: 0,
      rounded: 'sm',
    },
    VTextField: {
      color: 'primary',
      density: 'comfortable',
      variant: 'outlined',
    },
    VSelect: {
      color: 'primary',
      density: 'comfortable',
      variant: 'outlined',
    },
  },
})
