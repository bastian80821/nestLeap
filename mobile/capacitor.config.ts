import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "au.nestleap.app",
  appName: "NestLeap",
  webDir: "../frontend/out",
  ios: {
    contentInset: "always",
  },
  server: {
    // iOS uses capacitor:// scheme by default; the webview makes cross-origin
    // fetches to https://nestleap.au which is allowed by the backend's CORS=*.
    androidScheme: "https",
    iosScheme: "capacitor",
  },
};

export default config;
