# Deploying ReplayCloud

Runbook for the `ReplayCloud` stack (`infra/lib/cloud-stack.ts`), the cloud half of
[aws-migration.md](aws-migration.md). Builds run on hfbox; `cdk` and `aws` run on the
laptop with `AWS_PROFILE=replay` in `us-east-1`. hfbox never holds AWS credentials.
The `ReplayData` / `ReplayPipeline` skeletons ([aws-integrations.md](aws-integrations.md))
are not deployed: they exist in the CDK app only with `-c skeletons=true`.

## What gets created

| Resource                         | Notes                                                                                                                                                                    |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `Media` S3 bucket                | private, SSE-S3, TLS only, CORS PUT/GET/HEAD from the CloudFront origin (exposes `ETag`), aborts incomplete multipart uploads after 1 day. **Retained** on stack delete. |
| `Web` S3 bucket                  | private, SSE-S3, TLS only; read only by CloudFront (OAC).                                                                                                                |
| `Site` CloudFront distribution   | PriceClass_100, HTTPS redirect, default `*.cloudfront.net` name. `/` = apps/web build, `/tvapp/` = apps/tv web build.                                                    |
| `SpaRewrite` CloudFront Function | viewer request: a path with no file extension becomes `/index.html`, or `/tvapp/index.html` under `/tvapp/`.                                                             |
| `DeployWeb` / `DeployTv`         | BucketDeployment of `infra/build/web` and `infra/build/tvapp`, plus `config.json` in each, then a CloudFront invalidation.                                               |
| `Api` Lambda                     | python3.12, arm64, 1024 MB, 30 s, handler `replay_api.lambda_handler.handler`, code `infra/build/api-lambda.zip`. No reserved concurrency.                               |
| `Api` Function URL               | auth `NONE`: the app checks `X-Replay-Key`, upload tokens and the worker key. No URL-level CORS; FastAPI does CORS from `REPLAY_CORS_ORIGINS`.                           |
| `ApiLogs` log group              | 1 week retention.                                                                                                                                                        |
| API role                         | S3 on the media bucket only (list, get/put/delete objects, multipart), `ssm:GetParameter(s)` on `/replay/*`, `kms:Decrypt` only through SSM for `/replay/*`.             |

Everything is tagged `project=replay`. No VPC, NAT, VPC endpoints, API Gateway, KMS CMK,
DynamoDB, RDS or ECR. There are no SSM parameters in the template: the secrets are created
by hand (step 3).

Lambda environment: `REPLAY_STORAGE=s3`, `REPLAY_JOBS=s3`, `REPLAY_S3_BUCKET=<media>`,
`REPLAY_SSM_PREFIX=/replay/`, `REPLAY_PUBLIC_WEB_BASE` and `REPLAY_CORS_ORIGINS` =
`https://<distribution>.cloudfront.net`, `REPLAY_DATA_DIR=/tmp/replay`, `REPLAY_PIPELINE=worker`.

Outputs: `ApiUrl` (Function URL without the trailing `/`), `WebUrl`, `MediaBucket`,
`WebBucket`, `DistributionId`.

## 1. Build on hfbox

From the laptop repo root, sync a copy to the box and build there:

```sh
rsync -a --delete --exclude /data/ --exclude node_modules --exclude .venv \
  --exclude test-results --exclude samples/real ./ hfbox:/workspace/wt/replay-deploy/
ssh hfbox 'cd /workspace/wt/replay-deploy && source /workspace/wt/replay-env/env.sh &&
  flock /workspace/wt/replay-env/.cpu.lock infra/scripts/build-api-lambda.sh &&
  flock /workspace/wt/replay-env/.cpu.lock infra/scripts/build-web.sh'
rsync -a --delete hfbox:/workspace/wt/replay-deploy/infra/build/ infra/build/
```

- `build-api-lambda.sh` wheels `courtcam` and `services/api`, then installs them and their
  runtime dependencies for `manylinux` aarch64 / CPython 3.12 (`--only-binary=:all:`),
  pinned to the versions in `uv.lock`. It drops boto3/botocore/s3transfer (the Lambda
  runtime has them), `tests/` and `__pycache__/`, fails above 250 MiB unzipped and prints
  the size (about 170 MiB, 60 MiB zipped). Dev dependency groups are never installed.
- `build-web.sh [API_BASE]` builds apps/web into `infra/build/web` and the apps/tv web build
  (`VITE_BASE=/tvapp/`, `--base /tvapp/`) into `infra/build/tvapp`. With `API_BASE` it bakes
  `VITE_REPLAY_API_BASE`. It always unsets `VITE_REPLAY_API_KEY` and `VITE_MOCK_API`: the
  bundles are public, so the API key must never be baked into them.

`infra/build/` is gitignored. `cdk synth`/`deploy` stop with a clear error naming the missing
file when a build output is absent.

## 2. Bootstrap (once per account and region)

```sh
export AWS_PROFILE=replay AWS_REGION=us-east-1
cd infra && npm ci
npx cdk bootstrap "aws://$(aws sts get-caller-identity --query Account --output text)/us-east-1"
```

Bootstrap creates the `CDKToolkit` stack (an assets bucket, an empty ECR repository and
roles); none of it has an idle cost beyond a few cents of asset storage.

## 3. Secrets (SSM SecureString, before the first deploy)

Three standard-tier SecureStrings under the AWS-managed `aws/ssm` key. The values come
straight from `openssl` through a pipe, so they never appear in shell history, in `ps`
output or on screen:

```sh
for name in api-key worker-key upload-token-secret; do
  openssl rand -hex 32 | tr -d '\n' |
    aws ssm put-parameter --name "/replay/$name" --type SecureString \
      --value file:///dev/stdin --no-overwrite >/dev/null
done
aws ssm describe-parameters --parameter-filters Key=Name,Option=BeginsWith,Values=/replay/ \
  --query 'Parameters[].[Name,Type]' --output table
```

The Lambda reads them once per cold start. To rotate one, re-run its `put-parameter` with
`--overwrite` instead of `--no-overwrite`, then force fresh cold starts:
`aws lambda update-function-configuration --function-name <Api function> --description "rotated $(date +%F)"`.

To hand a value to a client (TV key, worker key) write it to a 0600 file, never to the
terminal:

```sh
(umask 077; aws ssm get-parameter --name /replay/api-key --with-decryption \
  --query Parameter.Value --output text > ~/.replay-api-key)
```

## 4. Deploy

```sh
cd infra
npx cdk deploy ReplayCloud --outputs-file build/outputs.json
out() { aws cloudformation describe-stacks --stack-name ReplayCloud \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
curl -s "$(out ApiUrl)/healthz"
echo "$(out WebUrl)  $(out WebUrl)tvapp/"
```

### API base for the web builds

The deploy writes `/config.json` and `/tvapp/config.json` containing
`{"apiBase": "<ApiUrl>"}` (CloudFront invalidated on every deploy), so the builds do not need
the URL baked in. That file is the hook: a frontend that fetches `config.json` (relative to
its base) at startup and falls back to `VITE_REPLAY_API_BASE` works after a single deploy.

Until both frontends read it, do a second pass after the first deploy:

```sh
ssh hfbox "cd /workspace/wt/replay-deploy && source /workspace/wt/replay-env/env.sh &&
  flock /workspace/wt/replay-env/.cpu.lock infra/scripts/build-web.sh $(out ApiUrl)"
rsync -a --delete hfbox:/workspace/wt/replay-deploy/infra/build/ infra/build/
npx cdk deploy ReplayCloud   # only the two BucketDeployments change
```

## 5. hfbox remote runner

The runner pulls jobs from the API over HTTPS with the worker key; it needs no AWS
credentials. Fetch the key on the laptop into a 0600 file and copy it over:

```sh
(umask 077; aws ssm get-parameter --name /replay/worker-key --with-decryption \
  --query Parameter.Value --output text > /tmp/replay-worker-key)
scp /tmp/replay-worker-key hfbox:/workspace/wt/replay-env/worker-key && rm /tmp/replay-worker-key
ssh hfbox 'chmod 600 /workspace/wt/replay-env/worker-key'
API=$(out ApiUrl)
ssh hfbox "tmux new -d -s replay-runner 'cd /workspace/wt/replay-deploy &&
  source /workspace/wt/replay-env/env.sh &&
  export REPLAY_WORKER_KEY=\$(cat /workspace/wt/replay-env/worker-key) &&
  export REPLAY_DATA_DIR=/workspace/wt/replay-env/runner-data REPLAY_PIPELINE=worker &&
  PYTHONPATH=\$PWD/courtcam:\$PWD/services/api:\$PWD/services/worker:\$PWD/render \
  python -m replay_api.remote_runner --api $API 2>&1 | tee -a /workspace/wt/replay-env/runner.log'"
ssh hfbox 'tmux capture-pane -pt replay-runner | tail'
```

`replay_py` puts only courtcam and services/api on `PYTHONPATH`; without services/worker
`REPLAY_PIPELINE=worker` logs "replay_worker unavailable" and runs courtcam directly (no
content-hash cache, no worker GPU lock). Smoke test the live stack with
`scripts/cloud-smoke.py` (header has the usage).

Stop it with `ssh hfbox 'tmux kill-session -t replay-runner'`. After rotating
`worker-key`, copy the file again and restart the session.

## Cost (estimate, us-east-1, idle household use)

| Item                        | Usage assumption                                                             | Monthly                                            |
| --------------------------- | ---------------------------------------------------------------------------- | -------------------------------------------------- |
| Lambda requests + duration  | runner poll every 30 s = 86k requests, about 0.2 GB-s each, plus app traffic | $0 (always-free 1M requests / 400k GB-s)           |
| S3 requests                 | about 86k LISTs from the job queue poll, a few thousand GET/PUT              | about $0.45                                        |
| S3 storage                  | a few GB of games                                                            | about $0.05 to $0.25                               |
| S3 egress                   | presigned video GETs go straight from S3, not CloudFront                     | $0 under the account-wide 100 GB/month free egress |
| CloudFront + Function       | static apps, well under 1 TB / 10M requests / 2M function invocations        | $0 (always free)                                   |
| SSM parameters, aws/ssm key | 3 standard parameters, a few decrypts per cold start                         | $0                                                 |
| CloudWatch Logs             | tens of MB per month, 1 week retention                                       | $0 (5 GB free)                                     |
| CDK assets bucket           | zip and web assets of past deploys                                           | under $0.05                                        |
| **Total**                   |                                                                              | **about $0.50 to $1**                              |

The `replay-monthly-10usd` budget alerts at 50/80/100% actual and 100% forecast.

## Teardown

```sh
export AWS_PROFILE=replay AWS_REGION=us-east-1
ssh hfbox 'tmux kill-session -t replay-runner; rm -f /workspace/wt/replay-env/worker-key'
aws s3 rm "s3://$(out WebBucket)" --recursive     # deployed files are kept by default
MEDIA=$(out MediaBucket)
cd infra && npx cdk destroy ReplayCloud
# The media bucket is RETAINED (user data). Delete it only on purpose:
aws s3 rm "s3://$MEDIA" --recursive && aws s3api delete-bucket --bucket "$MEDIA"
for name in api-key worker-key upload-token-secret; do aws ssm delete-parameter --name "/replay/$name"; done
# Log groups Lambda created on its own (BucketDeployment handler):
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/ReplayCloud \
  --query 'logGroups[].logGroupName' --output text | xargs -rn1 aws logs delete-log-group --log-group-name
# Optional, last: the bootstrap stack (empty its assets bucket first).
```

## CI and local checks (no AWS access)

```sh
cd infra && npm ci && npx tsc --noEmit
npx cdk synth --quiet -c stubBuilds=true -c skeletons=true   # stubs replace the three build outputs
npm test                                                    # infra/test/cloud-stack.test.ts
```

`stubBuilds=true` swaps the Lambda zip for an inline stub and each web build for a one-line
`index.html`, so the template synthesizes without builds. Never deploy with it.
