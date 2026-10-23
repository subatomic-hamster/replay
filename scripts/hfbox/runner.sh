#!/bin/bash
# Copy of /workspace/wt/replay-env/runner.sh on hfbox (HANDOFF.md §6). Pulls jobs from the
# deployed API and runs the worker pipeline on the box. Keys are read from 0600 files on the
# box, never stored here. Start: tmux new -d -s replay-runner "bash /workspace/wt/replay-env/runner.sh"
cd /workspace/wt/replay-deploy || exit 1
source /workspace/wt/replay-env/env.sh
REPLAY_WORKER_KEY=$(cat /workspace/wt/replay-env/worker-key)
export REPLAY_WORKER_KEY REPLAY_DATA_DIR=/workspace/wt/replay-env/runner-data REPLAY_PIPELINE=worker
# voice triggers ("Replay, clip that") only run when an ASR model is set
export COURTCAM_ASR_MODEL=/workspace/wt/replay-env/hf/hub/models--openai--whisper-small/snapshots/973afd24965f72e36ca33b3055d56a652f456b4d
export PYTHONPATH=$PWD/courtcam:$PWD/services/api:$PWD/services/worker:$PWD/render
python -m replay_api.remote_runner --api https://a3pd2rqlfcehgeg4dn2gbswnqa0dozxj.lambda-url.us-east-1.on.aws 2>&1 | tee -a /workspace/wt/replay-env/runner.log
