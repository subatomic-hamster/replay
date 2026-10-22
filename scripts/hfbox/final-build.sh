#!/bin/bash
# Copy of /workspace/wt/replay-env/final-build.sh on hfbox (HANDOFF.md §5). Builds the deploy
# artifacts (API lambda, web, cdk synth) and the release APK from a snapshot in
# /workspace/wt/replay-deploy-next. The APK embeds the API key: never commit or upload it.
set -e
API=https://a3pd2rqlfcehgeg4dn2gbswnqa0dozxj.lambda-url.us-east-1.on.aws
L=/workspace/wt/replay-env
cd /workspace/wt/replay-deploy-next
source $L/env.sh
echo "== deploy build"
flock $L/.mem.lock flock $L/.cpu.lock bash -c "infra/scripts/build-api-lambda.sh && infra/scripts/build-web.sh $API"
(cd infra && npx cdk synth ReplayCloud --quiet)
echo "deploy-ok"
echo "== apk build"
source $L/android/env.sh
cd apps/tv
pnpm install --frozen-lockfile --offline
cd android
echo "sdk.dir=$ANDROID_HOME" > local.properties
export REPLAY_API_BASE=$API
REPLAY_API_KEY=$(cat $L/api-key)
export REPLAY_API_KEY
flock $L/.mem.lock flock $L/.cpu.lock ./gradlew --offline assembleRelease -PreactNativeArchitectures=armeabi-v7a
ls -la app/build/outputs/apk/release/app-release.apk
echo "apk-ok"
