#!/bin/bash
set -euo pipefail

build=${1:?Expected a PyCharm build number}
app=${2:?Expected an absolute destination for the app}
if [[ ! $build =~ ^[0-9]+(\.[0-9]+)+$ || $app != /*.app ]]; then
    echo "Expected a numeric build number and an absolute .app path." >&2
    exit 1
fi

check_app() {
    if [[ ! -x $1/Contents/bin/inspect.sh ]] ||
        ! jq -e --arg build "$2" '.productCode == "PY" and .buildNumber == $build' "$1/Contents/Resources/product-info.json" >/dev/null; then
        echo "Expected an inspectable PyCharm build $2 at $1." >&2
        return 1
    fi
}

if [[ ${3:-} == --retire-others ]]; then
    if [[ $app != "$PWD/ides/$build/PyCharm.app" || -L $PWD/ides || -L ${app%/*} || -L $app ]]; then
        exit 0
    fi
    check_app "$app" "$build"
    for previous in "$PWD"/ides/*/PyCharm.app; do
        directory=${previous%/*}
        number=${directory##*/}
        [[ $previous != "$app" && $number =~ ^[0-9]+(\.[0-9]+)+$ && ! -L $directory && ! -L $previous ]] || continue
        check_app "$previous" "$number" 2>/dev/null || continue
        # The next inspection clears system even if removal is interrupted after the rename.
        mkdir -p system
        retired=$(mktemp -d "$PWD/system/retired.XXXXXX")
        mv "$previous" "$retired/"
        rm -r "$retired"
        rmdir "$directory" 2>/dev/null || true
        echo "retired PyCharm build $number"
    done
    exit 0
fi

if [[ -e $app || -L $app ]]; then
    check_app "$app" "$build"
    exit 0
fi

case "$(uname -sm)" in
    'Darwin arm64') platform=macM1 ;;
    'Darwin x86_64') platform=mac ;;
    *) echo "The pinned PyCharm installer requires macOS." >&2; exit 1 ;;
esac

parent=$(dirname "$app")
mkdir -p "$parent"
work=$(mktemp -d "$parent/.pycharm-install.XXXXXX")
mounted=false
cleanup() {
    if "$mounted"; then
        hdiutil detach "$work/mount" >&2 || hdiutil detach -force "$work/mount" >&2 || return 1
    fi
    rm -r "$work"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
cd "$work"

download=(curl --fail --silent --show-error --location --retry 2 --connect-timeout 30 --speed-limit 1024 --speed-time 60
    --proto '=https' --proto-redir '=https')
"${download[@]}" "https://data.services.jetbrains.com/products/releases?code=PCP&type=release,rc&build=$build" -o release.json
artifact=$(jq -ce --arg build "$build" --arg platform "$platform" '.PCP[] | select(.build == $build) | .downloads[$platform] // empty' release.json) ||
    { echo "JetBrains did not list PyCharm $build for $platform." >&2; exit 1; }
url=$(jq -er '.link' <<<"$artifact")
checksum_url=$(jq -er '.checksumLink' <<<"$artifact")
"${download[@]}" "$checksum_url" -o vendor.sha256
"${download[@]}" "$url" -o PyCharm.dmg
read -r checksum _ <vendor.sha256
printf '%s  PyCharm.dmg\n' "$checksum" | shasum -a 256 -c - >&2

mkdir mount
hdiutil attach -readonly -nobrowse -mountpoint "$work/mount" PyCharm.dmg >&2
mounted=true
ditto mount/PyCharm.app PyCharm.app
check_app "$work/PyCharm.app" "$build"
mv PyCharm.app "$app"
