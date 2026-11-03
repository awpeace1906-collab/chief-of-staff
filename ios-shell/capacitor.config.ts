import type { CapacitorConfig } from '@capacitor/cli';

// The WebView loads the live server (not bundled files), so relative /api calls and the sign-in
// cookie work exactly as in the PWA. Set COS_SERVER_URL before `npx cap sync ios`.
const SERVER = process.env.COS_SERVER_URL || 'http://localhost:8700';

const config: CapacitorConfig = {
  appId: 'com.yourdomain.chiefofstaff',      // replace with your bundle id (must match the portal App ID)
  appName: 'Chief of Staff',
  webDir: 'www',                              // offline fallback page only
  server: {
    url: SERVER,
    cleartext: SERVER.startsWith('http://'),  // dev only; production must be https
  },
  ios: { scheme: 'ChiefOfStaff', contentInset: 'always' },
};

export default config;
