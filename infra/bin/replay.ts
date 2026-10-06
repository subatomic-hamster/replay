// Env-agnostic stacks (no account/region): `cdk synth` needs no AWS credentials.
// Deploying later: set CDK_DEFAULT_ACCOUNT/REGION via `aws configure` and `cdk deploy --all`.
import { App } from "aws-cdk-lib";
import { DataStack } from "../lib/data-stack";
import { PipelineStack } from "../lib/pipeline-stack";

const app = new App();
const data = new DataStack(app, "ReplayData");
new PipelineStack(app, "ReplayPipeline", {
  bucket: data.bucket,
  tables: data.tables,
});
app.synth();
