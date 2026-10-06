#!/usr/bin/env bash
# Offline checks of the Fire TV scene renderer (com.replaytv.scene), no device needed:
#  1. every shader in app/src/main/assets/scene compiles as GLSL ES 1.00 (glslangValidator;
#     the external-texture sampler included);
#  2. SceneMath (camera, projection, billboards, frame index) against the synthetic fixture,
#     compiled with the Kotlin compiler from the Gradle cache and run on the JVM (the offline
#     cache has no JUnit, so app/src/test/.../SceneMathCheck.kt is a main()).
# Usage: bash apps/tv/android/scene-check.sh   (GRADLE_USER_HOME and JAVA_HOME from
# /workspace/wt/replay-env/android/env.sh on the box). Exit code 0 = all passed.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
fail=0

echo "=== shaders (glslangValidator)"
for s in "$here"/app/src/main/assets/scene/*.vert "$here"/app/src/main/assets/scene/*.frag; do
  if out=$(glslangValidator "$s" 2>&1); then
    echo "ok   $(basename "$s")"
  else
    echo "FAIL $(basename "$s")"
    echo "$out"
    fail=1
  fi
done

echo "=== SceneMath (Kotlin on the JVM)"
cache=${GRADLE_USER_HOME:?source the android env}/caches/modules-2/files-2.1
jar() { find "$cache/$1" -name "$2" | sort | tail -1; }
kv=2.2.0
cp=$(jar org.jetbrains.kotlin/kotlin-compiler-embeddable "kotlin-compiler-embeddable-$kv.jar")
for dep in kotlin-stdlib kotlin-script-runtime kotlin-reflect kotlin-daemon-embeddable; do
  cp+=:$(jar "org.jetbrains.kotlin/$dep" "$dep-$kv.jar")
done
cp+=:$(jar org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm "kotlinx-coroutines-core-jvm-*.jar")
cp+=:$(jar org.jetbrains/annotations "annotations-*.jar")
stdlib=$(jar org.jetbrains.kotlin/kotlin-stdlib "kotlin-stdlib-$kv.jar")
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
"$JAVA_HOME/bin/java" -cp "$cp" org.jetbrains.kotlin.cli.jvm.K2JVMCompiler -no-stdlib -no-reflect \
  -cp "$stdlib" -d "$out" -nowarn \
  "$here/app/src/main/java/com/replaytv/scene/SceneMath.kt" \
  "$here/app/src/test/java/com/replaytv/scene/SceneMathCheck.kt"
"$JAVA_HOME/bin/java" -cp "$out:$stdlib" com.replaytv.scene.SceneMathCheckKt || fail=1

exit $fail
