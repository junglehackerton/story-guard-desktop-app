#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_PATH="$PROJECT_DIR/src-tauri/target/release/bundle/macos/Story Guard.app"
VERSION="$(node -p "JSON.parse(require('fs').readFileSync('src-tauri/tauri.conf.json','utf8')).version")"
ARCH="$(uname -m)"
OUTPUT_PATH="${1:-$PROJECT_DIR/output/releases/Story Guard_${VERSION}_${ARCH}.dmg}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS에서만 DMG를 만들 수 있습니다." >&2
  exit 2
fi

npm --prefix "$PROJECT_DIR" run tauri build -- --bundles app
if [[ ! -d "$APP_PATH" ]]; then
  echo "앱 번들을 찾을 수 없습니다." >&2
  exit 1
fi

stage_dir="$(mktemp -d "${TMPDIR:-/tmp}/storyguard-dmg.XXXXXX")"
trap 'rm -rf "$stage_dir"' EXIT
cp -R "$APP_PATH" "$stage_dir/"
# Finder 장식 없이도 설치 위치를 명확히 보여 주는 표준 Applications 링크를
# 포함한다. create-dmg의 resize/AppleScript 단계는 잠금·CI 환경에서 실패할
# 수 있으므로, hdiutil의 기본 생성 경로만 사용해 재현성을 보장한다.
ln -s /Applications "$stage_dir/Applications"
mkdir -p "$(dirname "$OUTPUT_PATH")"

# Finder의 위치 지정 AppleScript나 resize 단계에 의존하지 않는 비GUI DMG다.
# macOS 일부 환경에서는 `hdiutil create`가 장치 오류를 반환하므로,
# makehybrid로 만든 읽기 전용 이미지를 바로 UDZO로 변환한다.
rm -f "$OUTPUT_PATH"
hybrid_path="${OUTPUT_PATH%.dmg}.hybrid.dmg"
rm -f "$hybrid_path"
hdiutil makehybrid -quiet -o "$hybrid_path" -hfs \
  -default-volume-name "Story Guard" "$stage_dir"
hdiutil convert "$hybrid_path" -format UDZO -ov -o "$OUTPUT_PATH"
rm -f "$hybrid_path"

# `imageinfo` can fail in a restricted runner because it tries to configure a
# device. `verify` reads the image checksum without mounting it and is the
# integrity gate used for the release manifest.
hdiutil verify "$OUTPUT_PATH"
SHA256="$(shasum -a 256 "$OUTPUT_PATH" | awk '{print $1}')"
echo "$SHA256  $OUTPUT_PATH"

# Keep the human-readable release note and machine-readable manifest in sync
# with custom output paths as well as the default DMG name.
python3 - "$PROJECT_DIR" "$OUTPUT_PATH" "$VERSION" "$ARCH" "$SHA256" <<'PY'
import json
import re
import sys
from pathlib import Path

project_dir, output_path, version, architecture, sha256 = sys.argv[1:]
root = Path(project_dir)
manifest_path = root / "output" / "releases" / "release.json"
manifest_path.parent.mkdir(parents=True, exist_ok=True)
manifest = {
    "product": "Story Guard",
    "version": version,
    "platform": "macOS",
    "architecture": architecture,
    "file": Path(output_path).name,
    "sha256": sha256,
    "signed": False,
    "notarized": False,
    "verified": True,
    "status": "development-release",
    "generatedBy": "scripts/build-macos-dmg.sh",
}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

readme_path = root / "output" / "releases" / "README.md"
if readme_path.exists():
    text = readme_path.read_text(encoding="utf-8")
else:
    text = "# Story Guard macOS release\n\n"
text = re.sub(r"^- 파일: `[^`]+`$", f"- 파일: `{Path(output_path).name}`", text, count=1, flags=re.MULTILINE)
text = re.sub(r"^- 대상: .*$", f"- 대상: Apple Silicon arm64" if architecture == "arm64" else f"- 대상: macOS {architecture}", text, count=1, flags=re.MULTILINE)
text = re.sub(r"^- SHA-256: `[^`]+`$", f"- SHA-256: `{sha256}`", text, count=1, flags=re.MULTILINE)
readme_path.write_text(text, encoding="utf-8")
PY
echo "DMG 생성 완료: $OUTPUT_PATH"
