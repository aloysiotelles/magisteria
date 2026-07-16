import type { CapacitorConfig } from '@capacitor/cli';

// Placeholder until the owner confirms the final reverse-domain identifier.
const appId = process.env.CAPACITOR_APP_ID?.trim() || 'br.com.seudominio.magisteria';

const config: CapacitorConfig = {
  appId,
  appName: 'MAGISTERIA',
  webDir: 'mobile/dist',
  server: {
    hostname: 'localhost',
    androidScheme: 'https',
    iosScheme: 'capacitor',
  },
  android: {
    allowMixedContent: false,
    captureInput: true,
  },
  ios: {
    contentInset: 'automatic',
    preferredContentMode: 'mobile',
    limitsNavigationsToAppBoundDomains: true,
  },
  plugins: {
    Keyboard: {
      resize: 'body',
      style: 'dark',
      resizeOnFullScreen: true,
    },
    SplashScreen: {
      launchAutoHide: false,
      launchShowDuration: 3000,
      backgroundColor: '#f4efe5',
      showSpinner: false,
      androidScaleType: 'CENTER_CROP',
    },
  },
};

export default config;
