// ReplayCloud template checks (node:test via tsx; synth with stub builds, no AWS access).
import assert from "node:assert/strict";
import { test } from "node:test";
import { App } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { CloudStack } from "../lib/cloud-stack";

const stack = new CloudStack(new App(), "ReplayCloud", {
  apiZip: "unused",
  webDir: "unused",
  tvDir: "unused",
  stubBuilds: true,
});
const t = Template.fromStack(stack);
const json = t.toJSON() as { Resources: Record<string, { Type: string }> };
const mediaId =
  Object.keys(t.findResources("AWS::S3::Bucket")).find((id) =>
    id.startsWith("Media"),
  ) ?? "";

test("both buckets block all public access and stay private", () => {
  const buckets = t.findResources("AWS::S3::Bucket");
  assert.equal(Object.keys(buckets).length, 2);
  for (const b of Object.values(buckets)) {
    assert.deepEqual(b.Properties.PublicAccessBlockConfiguration, {
      BlockPublicAcls: true,
      BlockPublicPolicy: true,
      IgnorePublicAcls: true,
      RestrictPublicBuckets: true,
    });
  }
  assert.ok(mediaId, "media bucket present");
  assert.equal(buckets[mediaId].DeletionPolicy, "Retain");
  t.hasResourceProperties("AWS::S3::Bucket", {
    LifecycleConfiguration: {
      Rules: [
        Match.objectLike({
          AbortIncompleteMultipartUpload: { DaysAfterInitiation: 1 },
        }),
      ],
    },
    CorsConfiguration: {
      CorsRules: [
        Match.objectLike({ ExposedHeaders: Match.arrayWith(["ETag"]) }),
      ],
    },
  });
});

test("API Lambda is python3.12 on arm64 with the Mangum handler", () => {
  t.hasResourceProperties("AWS::Lambda::Function", {
    Runtime: "python3.12",
    Architectures: ["arm64"],
    MemorySize: 1024,
    Timeout: 30,
    Handler: "replay_api.lambda_handler.handler",
    Environment: {
      Variables: Match.objectLike({
        REPLAY_STORAGE: "s3",
        REPLAY_JOBS: "s3",
        REPLAY_SSM_PREFIX: "/replay/",
      }),
    },
  });
  const api = Object.values(t.findResources("AWS::Lambda::Function")).find(
    (f) => f.Properties.Handler === "replay_api.lambda_handler.handler",
  )!;
  assert.equal(api.Properties.ReservedConcurrentExecutions, undefined);
});

test("Function URL is public (app-enforced keys) with no URL-level CORS", () => {
  t.resourceCountIs("AWS::Lambda::Url", 1);
  t.hasResourceProperties("AWS::Lambda::Url", {
    AuthType: "NONE",
    Cors: Match.absent(),
  });
});

test("no idle-cost or out-of-scope resources", () => {
  const banned =
    /^AWS::(EC2|RDS|DynamoDB|ApiGateway|ApiGatewayV2|KMS|ECR|SSM|SecretsManager|ElastiCache|WAFv2)::/;
  const hits = Object.values(json.Resources)
    .map((r) => r.Type)
    .filter((ty) => banned.test(ty));
  assert.deepEqual(hits, []);
});

test("API role S3 access is scoped to the media bucket; SSM to /replay/*", () => {
  const apiRoleId = Object.keys(t.findResources("AWS::IAM::Role")).find((id) =>
    id.startsWith("ApiServiceRole"),
  )!;
  const policies = Object.values(t.findResources("AWS::IAM::Policy")).filter(
    (p) => p.Properties.Roles.some((r: any) => r.Ref === apiRoleId),
  );
  const statements = policies.flatMap(
    (p) => p.Properties.PolicyDocument.Statement,
  );
  const actions = (s: any): string[] => [s.Action].flat();
  const s3 = statements.filter((s) =>
    actions(s).some((a) => a.startsWith("s3:")),
  );
  assert.ok(s3.length >= 2);
  for (const s of s3) {
    const text = JSON.stringify(s.Resource);
    assert.ok(
      text.includes(mediaId),
      `S3 statement not scoped to the media bucket: ${text}`,
    );
    assert.ok(!text.includes('"*"') && s.Resource !== "*");
  }
  const ssm = statements.filter((s) =>
    actions(s).some((a) => a.startsWith("ssm:")),
  );
  assert.equal(ssm.length, 1);
  assert.match(JSON.stringify(ssm[0].Resource), /parameter\/replay\/\*/);
  const kms = statements.find((s) => actions(s).includes("kms:Decrypt"))!;
  assert.ok(kms.Condition.StringEquals["kms:ViaService"]);
});
