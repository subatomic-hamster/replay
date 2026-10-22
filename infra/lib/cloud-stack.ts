// The deployed cloud (docs/aws-migration.md, docs/aws-deploy.md): private media bucket,
// both web builds behind CloudFront (OAC), the API as one arm64 Lambda behind a Function
// URL. Nothing here has idle cost: no VPC, NAT, API Gateway, KMS CMK, tables or images.
// Secrets live in SSM SecureString parameters created out-of-band; never in this template.
import { existsSync } from "node:fs";
import {
  CfnOutput,
  Duration,
  Fn,
  RemovalPolicy,
  Stack,
  Tags,
  type StackProps,
} from "aws-cdk-lib";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import type { Construct } from "constructs";

export interface CloudProps extends StackProps {
  /** infra/build/api-lambda.zip from infra/scripts/build-api-lambda.sh */
  apiZip: string;
  /** apps/web build (served at /) and apps/tv web build (served at /tvapp/) */
  webDir: string;
  tvDir: string;
  /** synth-only placeholders instead of the three build outputs (CI, tests) */
  stubBuilds?: boolean;
}

export const SSM_PREFIX = "/replay/";

// SPA routing for two apps in one bucket: extension-less paths fall back to the owning
// app's index.html. /config.json and assets have an extension and pass through.
const SPA_REWRITE = `function handler(event) {
  var r = event.request, u = r.uri;
  if (u === "/tvapp") return { statusCode: 301, statusDescription: "Moved", headers: { location: { value: "/tvapp/" } } };
  if (u.lastIndexOf(".") > u.lastIndexOf("/")) return r;
  r.uri = u.indexOf("/tvapp/") === 0 ? "/tvapp/index.html" : "/index.html";
  return r;
}`;

function need(path: string, how: string): string {
  if (!existsSync(path)) {
    throw new Error(
      `ReplayCloud: missing ${path}. ${how} (docs/aws-deploy.md), or synth with -c stubBuilds=true for a template-only check.`,
    );
  }
  return path;
}

export class CloudStack extends Stack {
  constructor(scope: Construct, id: string, props: CloudProps) {
    super(scope, id, props);
    Tags.of(this).add("project", "replay");
    const stub = props.stubBuilds ?? false;

    // --- web: private bucket, CloudFront with OAC -------------------------------------
    const webBucket = new s3.Bucket(this, "Web", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      // build output only; re-deployable at any time
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: false,
    });
    const distribution = new cloudfront.Distribution(this, "Site", {
      comment: "Replay web (/) and TV web (/tvapp/)",
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      defaultRootObject: "index.html",
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(webBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        functionAssociations: [
          {
            eventType: cloudfront.FunctionEventType.VIEWER_REQUEST,
            function: new cloudfront.Function(this, "SpaRewrite", {
              runtime: cloudfront.FunctionRuntime.JS_2_0,
              code: cloudfront.FunctionCode.fromInline(SPA_REWRITE),
            }),
          },
        ],
      },
    });
    const webOrigin = `https://${distribution.distributionDomainName}`;

    // --- media: games/, jobs/, profiles/ (user data: retained on stack delete) -----------
    const media = new s3.Bucket(this, "Media", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.RETAIN,
      autoDeleteObjects: false,
      cors: [
        {
          // phone multipart PUTs (needs ETag back), presigned GETs with Range for playback
          allowedMethods: [
            s3.HttpMethods.PUT,
            s3.HttpMethods.GET,
            s3.HttpMethods.HEAD,
          ],
          allowedOrigins: [webOrigin],
          allowedHeaders: ["*"],
          exposedHeaders: [
            "ETag",
            "Content-Range",
            "Accept-Ranges",
            "Content-Length",
          ],
          maxAge: 3600,
        },
      ],
      lifecycleRules: [
        { abortIncompleteMultipartUploadAfter: Duration.days(1) },
      ],
    });

    // --- API: FastAPI via Mangum on one Lambda, Function URL --------------------------------
    const api = new lambda.Function(this, "Api", {
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      memorySize: 1024,
      timeout: Duration.seconds(30),
      handler: "replay_api.lambda_handler.handler",
      code: stub
        ? lambda.Code.fromInline(
            "def handler(event, context):\n    raise RuntimeError('stub build')\n",
          )
        : lambda.Code.fromAsset(
            need(
              props.apiZip,
              "Run infra/scripts/build-api-lambda.sh on hfbox",
            ),
          ),
      logGroup: new logs.LogGroup(this, "ApiLogs", {
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: RemovalPolicy.DESTROY,
      }),
      environment: {
        REPLAY_STORAGE: "s3",
        REPLAY_JOBS: "s3",
        REPLAY_S3_BUCKET: media.bucketName,
        REPLAY_SSM_PREFIX: SSM_PREFIX,
        REPLAY_PUBLIC_WEB_BASE: webOrigin,
        REPLAY_CORS_ORIGINS: webOrigin,
        REPLAY_DATA_DIR: "/tmp/replay",
        REPLAY_PIPELINE: "worker",
        // the opt-in stages the hfbox runner runs (docs/aws-deploy.md §5): readiness shows
        // their features as `pending` while a game processes. Keep in step with the runner.
        REPLAY_WORKER_STAGES: "hype,condensed,replays,scene",
      },
    });
    // The app checks X-Replay-Key / upload tokens / worker key itself; CORS is FastAPI's.
    const apiUrl = api.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
    });
    // The URL ends in "/"; clients join paths onto it, so publish it without one.
    const apiBase = `https://${Fn.select(2, Fn.split("/", apiUrl.url))}`;

    // Least privilege: this bucket only (objects, listing, multipart), /replay/* parameters.
    api.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["s3:ListBucket", "s3:ListBucketMultipartUploads"],
        resources: [media.bucketArn],
      }),
    );
    api.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:AbortMultipartUpload",
          "s3:ListMultipartUploadParts",
        ],
        resources: [media.arnForObjects("*")],
      }),
    );
    const paramArn = this.formatArn({
      service: "ssm",
      resource: "parameter",
      resourceName: `${SSM_PREFIX.slice(1)}*`,
    });
    api.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["ssm:GetParameter", "ssm:GetParameters"],
        resources: [paramArn],
      }),
    );
    // SecureStrings use the AWS-managed aws/ssm key: decrypt only through SSM, only for
    // our parameters (SSM passes the parameter ARN as encryption context).
    api.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["kms:Decrypt"],
        resources: [
          this.formatArn({
            service: "kms",
            resource: "key",
            resourceName: "*",
          }),
        ],
        conditions: {
          StringEquals: {
            "kms:ViaService": `ssm.${this.region}.amazonaws.com`,
          },
          StringLike: { "kms:EncryptionContext:PARAMETER_ARN": paramArn },
        },
      }),
    );

    // --- web content + runtime config hook --------------------------------------------------
    // /config.json and /tvapp/config.json carry the API base so the builds need no baked URL
    // (frontends: fetch it at startup, fall back to VITE_REPLAY_API_BASE).
    const config = s3deploy.Source.jsonData("config.json", {
      apiBase,
    });
    const site = (dir: string) =>
      stub
        ? s3deploy.Source.data(
            "index.html",
            "<!doctype html><title>stub</title>",
          )
        : s3deploy.Source.asset(
            need(dir, "Run infra/scripts/build-web.sh on hfbox"),
          );
    new s3deploy.BucketDeployment(this, "DeployWeb", {
      sources: [site(props.webDir), config],
      destinationBucket: webBucket,
      exclude: ["tvapp/*"], // owned by DeployTv; also keeps prune off it
      distribution,
      distributionPaths: ["/*"],
      memoryLimit: 512,
    });
    new s3deploy.BucketDeployment(this, "DeployTv", {
      sources: [site(props.tvDir), config],
      destinationBucket: webBucket,
      destinationKeyPrefix: "tvapp/",
      distribution,
      distributionPaths: ["/tvapp/*"],
      memoryLimit: 512,
    });

    new CfnOutput(this, "ApiUrl", { value: apiBase });
    new CfnOutput(this, "WebUrl", { value: `${webOrigin}/` });
    new CfnOutput(this, "MediaBucket", { value: media.bucketName });
    new CfnOutput(this, "WebBucket", { value: webBucket.bucketName });
    new CfnOutput(this, "DistributionId", {
      value: distribution.distributionId,
    });
  }
}
