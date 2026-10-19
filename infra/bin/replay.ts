// Env-agnostic stacks (no account/region): `cdk synth` needs no AWS credentials.
// ReplayCloud is the deployed stack (docs/aws-deploy.md): `cdk deploy ReplayCloud`.
// The ReplayData/ReplayPipeline skeletons (docs/aws-integrations.md) are synth-only and exist
// in the app only with `-c skeletons=true`, so they can never ride along on a deploy.
// Context: apiZip, webDir, tvDir (default infra/build/...), stubBuilds=true (no build outputs).
import { resolve } from "node:path";
import { App } from "aws-cdk-lib";
import { CloudStack } from "../lib/cloud-stack";
import { DataStack } from "../lib/data-stack";
import { PipelineStack } from "../lib/pipeline-stack";

const app = new App();
const ctx = (key: string): string | undefined => app.node.tryGetContext(key);
const build = (key: string, rel: string) =>
  resolve(ctx(key) ?? resolve(__dirname, "../build", rel));

new CloudStack(app, "ReplayCloud", {
  apiZip: build("apiZip", "api-lambda.zip"),
  webDir: build("webDir", "web"),
  tvDir: build("tvDir", "tvapp"),
  stubBuilds: String(ctx("stubBuilds")) === "true",
  description:
    "Replay cloud: API Lambda + Function URL, media bucket, web on CloudFront",
});

if (String(ctx("skeletons")) === "true") {
  const data = new DataStack(app, "ReplayData");
  new PipelineStack(app, "ReplayPipeline", {
    bucket: data.bucket,
    tables: data.tables,
  });
}
app.synth();
