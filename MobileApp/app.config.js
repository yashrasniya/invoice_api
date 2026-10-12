// Wraps app.json. Android push notifications need Firebase: when google-services.json is present next to
// this file it is wired in automatically; when it is absent the app still builds (push just isn't available).
const fs = require('fs');
const path = require('path');

module.exports = ({ config }) => {
  const hasGoogleServices = fs.existsSync(path.join(__dirname, 'google-services.json'));
  return {
    ...config,
    android: {
      ...config.android,
      ...(hasGoogleServices ? { googleServicesFile: './google-services.json' } : {}),
    },
  };
};
