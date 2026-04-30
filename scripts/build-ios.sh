#!/usr/bin/env bash
# Build the iOS app: static-export the Next.js frontend, then sync into the
# Capacitor Xcode project. Run this whenever the frontend changes.
#
# Usage:
#   ./scripts/build-ios.sh                # production build, points at https://nestleap.au
#   API_URL=http://192.168.x.x:8000 ./scripts/build-ios.sh   # dev build against local backend

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_URL="${API_URL:-https://nestleap.au}"

echo "→ Building Next.js static export (API_URL=$API_URL)"
cd "$REPO_ROOT/frontend"
BUILD_TARGET=mobile NEXT_PUBLIC_API_URL="$API_URL" npm run build

echo "→ Syncing into Capacitor iOS project"
cd "$REPO_ROOT/mobile"
npx cap sync ios

echo
echo "✓ Done. Open the workspace with:"
echo "    open $REPO_ROOT/mobile/ios/App/App.xcworkspace"
