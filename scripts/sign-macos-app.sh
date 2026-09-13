#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_PATH="${APP_PATH:-$ROOT_DIR/src-tauri/target/release/bundle/macos/Story Guard.app}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS에서만 앱 서명을 실행할 수 있습니다." >&2
  exit 1
fi
if [[ ! -d "$APP_PATH" ]]; then
  echo "앱 번들을 찾을 수 없습니다: $APP_PATH" >&2
  exit 1
fi
if [[ -z "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  echo "APPLE_SIGNING_IDENTITY를 지정하세요. 예: Developer ID Application: Team Name (TEAMID)" >&2
  exit 1
fi

codesign --force --deep --options runtime --timestamp --sign "$APPLE_SIGNING_IDENTITY" "$APP_PATH"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

if [[ "${NOTARIZE:-0}" == "1" ]]; then
  if [[ -z "${APPLE_NOTARY_PROFILE:-}" ]]; then
    echo "공증에는 APPLE_NOTARY_PROFILE이 필요합니다. notarytool store-credentials 프로필을 지정하세요." >&2
    exit 1
  fi
  ZIP_PATH="${APP_PATH%.app}.zip"
  ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"
  xcrun notarytool submit "$ZIP_PATH" --keychain-profile "$APPLE_NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP_PATH"
  xcrun stapler validate "$APP_PATH"
  rm -f "$ZIP_PATH"
fi

echo "서명 완료: $APP_PATH"
if [[ "${NOTARIZE:-0}" == "1" ]]; then
  echo "공증·staple 완료"
else
  echo "공증은 실행하지 않았습니다. 공개 배포 전 NOTARIZE=1로 다시 실행하세요."
fi
