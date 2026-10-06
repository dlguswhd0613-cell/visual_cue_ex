#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
build_dir="$(mktemp -d)"
trap 'rm -rf "$build_dir"' EXIT
c++ -std=c++11 -O2 -Wall -Wextra -I "$repo_dir/tests/firmware" \
  "$repo_dir/tests/firmware/test.cpp" -o "$build_dir/firmware-tests"
"$build_dir/firmware-tests"
