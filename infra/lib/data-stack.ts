// S3 media bucket + DynamoDB tables: the targets of the `storage`, `index` and `jobs`
// providers (services/api/replay_api/providers/aws.py) and of profiles (vision §21).
import { RemovalPolicy, Stack, type StackProps } from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as s3 from "aws-cdk-lib/aws-s3";
import type { Construct } from "constructs";

export interface Tables {
  games: dynamodb.Table;
  profiles: dynamodb.Table;
  jobs: dynamodb.Table;
}

export class DataStack extends Stack {
  readonly bucket: s3.Bucket;
  readonly tables: Tables;

  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    // games/{game_id}/... mirrors data/games/{game_id}/ on disk.
    this.bucket = new s3.Bucket(this, "Media", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      cors: [
        {
          // HTTP Range for progressive MP4 playback (D-3) via presigned GETs
          allowedMethods: [s3.HttpMethods.GET, s3.HttpMethods.HEAD],
          allowedOrigins: ["*"],
          allowedHeaders: ["Range"],
          exposedHeaders: ["Content-Range", "Accept-Ranges", "Content-Length"],
        },
      ],
      removalPolicy: RemovalPolicy.RETAIN,
    });

    const table = (name: string, pk: string) =>
      new dynamodb.Table(this, name, {
        partitionKey: { name: pk, type: dynamodb.AttributeType.STRING },
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        removalPolicy: RemovalPolicy.RETAIN,
      });

    const games = table("Games", "id");
    games.addGlobalSecondaryIndex({
      indexName: "by_recorded_at",
      partitionKey: { name: "owner", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "recorded_at", type: dynamodb.AttributeType.STRING },
    });
    const profiles = table("Profiles", "profile_id");
    const jobs = table("Jobs", "id");
    jobs.addGlobalSecondaryIndex({
      indexName: "by_game",
      partitionKey: { name: "game_id", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "created_at", type: dynamodb.AttributeType.NUMBER },
    });
    this.tables = { games, profiles, jobs };
  }
}
