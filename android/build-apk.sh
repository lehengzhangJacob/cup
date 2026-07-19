#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS="${ANDROID_BUILD_TOOLS:-/home/gmn/.cache/cup-android}"
DOWNLOADS="$TOOLS/downloads"
JAVA_HOME="${JAVA_HOME:-$TOOLS/jdk-root/usr/lib/jvm/java-17-openjdk-amd64}"
ANDROID_HOME="${ANDROID_HOME:-$TOOLS/sdk}"
GRADLE_HOME="$TOOLS/gradle-8.2"

export JAVA_HOME ANDROID_HOME
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"

while IFS= read -r -d '' link; do
  target="$(readlink "$link")"
  local_target="$TOOLS/jdk-root$target"
  if [[ -f "$local_target" ]]; then
    cp --remove-destination "$local_target" "$link"
  fi
done < <(find "$JAVA_HOME" -type l -lname '/etc/java-17-openjdk/*' -print0)

if [[ ! -f "$JAVA_HOME/lib/security/cacerts" ]]; then
  CACERTS="$TOOLS/jdk-cacerts"
  if [[ ! -f "$CACERTS" ]]; then
    for certificate in /etc/ssl/certs/*.pem; do
      alias_name="$(basename "$certificate" .pem)"
      "$JAVA_HOME/bin/keytool" -importcert -noprompt -trustcacerts \
        -alias "$alias_name" -file "$certificate" \
        -keystore "$CACERTS" -storepass changeit >/dev/null 2>&1 || true
    done
  fi
  cp --remove-destination "$CACERTS" "$JAVA_HOME/lib/security/cacerts"
fi

export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:-} -Djavax.net.ssl.trustStore=$JAVA_HOME/lib/security/cacerts -Djavax.net.ssl.trustStorePassword=changeit"

if [[ ! -x "$JAVA_HOME/bin/java" ]]; then
  echo "JDK 17 is missing: $JAVA_HOME" >&2
  exit 1
fi

if [[ ! -x "$GRADLE_HOME/bin/gradle" ]]; then
  unzip -q "$DOWNLOADS/gradle-8.2-bin.zip" -d "$TOOLS"
fi

if [[ ! -x "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ]]; then
  mkdir -p "$ANDROID_HOME/cmdline-tools/latest" "$TOOLS/cmdline-tools-unpack"
  unzip -q "$DOWNLOADS/commandlinetools-linux-14742923_latest.zip" -d "$TOOLS/cmdline-tools-unpack"
  cp -a "$TOOLS/cmdline-tools-unpack/cmdline-tools/." "$ANDROID_HOME/cmdline-tools/latest/"
fi

SDKMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
yes | "$SDKMANAGER" --licenses >/dev/null 2>&1 || true
"$SDKMANAGER" "platform-tools" "platforms;android-34" "build-tools;34.0.0"

printf 'sdk.dir=%s\n' "$ANDROID_HOME" > "$ROOT/android/local.properties"

cd "$ROOT/android"
if [[ ! -x gradlew ]]; then
  "$GRADLE_HOME/bin/gradle" --no-daemon wrapper
fi
"$GRADLE_HOME/bin/gradle" --no-daemon clean assembleRelease

APK_SOURCE="$ROOT/android/app/build/outputs/apk/release/app-release.apk"
APK_TARGET="$ROOT/services/api/static/downloads/lingshan-guide-v1.0.1.apk"
cp "$APK_SOURCE" "$APK_TARGET"
sha256sum "$APK_TARGET"
