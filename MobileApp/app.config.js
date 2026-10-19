// Wraps app.json. Android push notifications need Firebase: when google-services.json is present next to
// this file it is wired in automatically; when it is absent the app still builds (push just isn't available).
const fs = require('fs');
const path = require('path');

// Size: release builds get R8 code shrinking + unused-resource removal (debug/dev-client builds are unaffected).
// The `preview` APK (for sideloading) is built for 64-bit ARM only — nearly every current phone — which drops the
// native libraries for the other three CPU types. `production` (the Play bundle) keeps every CPU type, and Play
// delivers each phone only the one it needs.
const buildProperties = [
  'expo-build-properties',
  {
    android: {
      enableMinifyInReleaseBuilds: true,
      enableShrinkResourcesInReleaseBuilds: true,
      ...(process.env.EAS_BUILD_PROFILE === 'preview' ? { buildArchs: ['arm64-v8a'] } : {}),
    },
  },
];

module.exports = ({ config }) => {
  const hasGoogleServices = fs.existsSync(path.join(__dirname, 'google-services.json'));
  const hasIosServices = fs.existsSync(path.join(__dirname, 'GoogleService-Info.plist'));
  return {
    ...config,
    // Phone sign-in (Firebase Auth) needs the Firebase config for the platform being built; without it the plugin
    // is left out and the login screen simply hides the phone option.
    plugins: [
      ...(config.plugins ?? []),
      buildProperties,
      ...(hasGoogleServices || hasIosServices ? ['@react-native-firebase/app', '@react-native-firebase/auth'] : []),
    ],
    ios: {
      ...config.ios,
      ...(hasIosServices ? { googleServicesFile: './GoogleService-Info.plist' } : {}),
    },
    android: {
      ...config.android,
      ...(hasGoogleServices ? { googleServicesFile: './google-services.json' } : {}),
    },
  };
};
