#!/usr/bin/env bash
# Install official Node 22 binaries for this user; no system Node replacement.
set -euo pipefail
case "$(uname -m)" in
  x86_64) arch=x64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) echo 'Unsupported CPU architecture'; exit 1 ;;
esac
mkdir -p "$HOME/.local/bin" "$HOME/.local/lib"
for binary in node npm npx; do
  if [ -e "$HOME/.local/bin/$binary" ] || [ -L "$HOME/.local/bin/$binary" ]; then
    echo "$HOME/.local/bin/$binary already exists; review it before installing."
    exit 1
  fi
done
work=$(mktemp -d)
cd "$work"
curl --fail --silent --show-error --location https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt -o SHASUMS256.txt
archive=$(awk -v arch="$arch" '$2 ~ ("^node-v22\\.[0-9]+\\.[0-9]+-linux-" arch "\\.tar\\.xz$") {print $2}' SHASUMS256.txt)
if [ -z "$archive" ] || [[ "$archive" == *$'\n'* ]]; then
  echo 'Could not select one official Node archive'; exit 1
fi
curl --fail --silent --show-error --location "https://nodejs.org/dist/latest-v22.x/$archive" -o "$archive"
awk -v file="$archive" '$2 == file' SHASUMS256.txt | sha256sum --check -
target="$HOME/.local/lib/${archive%.tar.xz}"
if [ -e "$target" ]; then
  echo "$target already exists; review it before installing."
  exit 1
fi
tar -xJf "$archive" -C "$HOME/.local/lib"
for binary in node npm npx; do
  ln -s "$target/bin/$binary" "$HOME/.local/bin/$binary"
done
export PATH="$HOME/.local/bin:$PATH"
node --version
npm --version
echo 'Add export PATH="$HOME/.local/bin:$PATH" to your shell profile.'
echo "Downloaded archive and checksum manifest remain in $work."
