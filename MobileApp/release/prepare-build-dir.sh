#!/usr/bin/env bash
# Copies ONLY the mobile app into a clean folder outside the git repo, so an EAS build can never
# upload anything else from the repository (backend, sample data, the old Android wrapper's keystore...).
# Why: EAS packages the whole git repo, applies the repo-wide `lib/` ignore rule (dropping this app's
# lib/ folder) and the app lives in a subfolder of a much larger repo.
#
#   ./release/prepare-build-dir.sh            -> prints the folder to build from
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${INVOICE_PRO_BUILD_DIR:-$HOME/invoice-pro-build}"

mkdir -p "$DEST"
rsync -a --delete \
  --exclude 'node_modules/' --exclude '.expo/' --exclude 'dist/' --exclude 'web-build/' \
  --exclude '.git/' --exclude '.DS_Store' \
  --exclude '.env' --exclude '.env.local' --exclude '.env.*.local' \
  --exclude '*.jks' --exclude '*.keystore' --exclude '*.p8' --exclude '*.p12' --exclude '*.key' --exclude '*.pem' \
  --exclude 'ios/' --exclude 'android/' \
  "$SRC/" "$DEST/"

echo "Prepared: $DEST"
echo "Next:"
echo "  cd \"$DEST\""
echo "  EAS_NO_VCS=1 eas build --profile preview --platform android"
