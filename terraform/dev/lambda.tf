# iam, lambda, dynamodb

resource "aws_s3_bucket" "default" {
  bucket = "codepipeline-slack-bot-dev-ap-northeast-2-7162e6c8"
  acl    = "private"

  tags = {
    Name = "codepipline slack bot s3"
  }
}

module "lambda_function" {
  source = "terraform-aws-modules/lambda/aws"
  version = "2.7.0"

  function_name = "codepipeline-slack-bot"
  description   = "codepipline status to slack function"
  handler       = "notifier.run"
  runtime       = "python3.7"
  publish       = true

  source_path = [
    {
      path             = "../../src/"
    }
  ]

  store_on_s3 = true
  s3_bucket   = aws_s3_bucket.default.id

  environment_variables = { for tuple in regexall("(.*)=(.*)", file("../../.env")) : tuple[0] => tuple[1] }

  attach_policy_json = true
  policy_json = <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Action": [
                "logs:CreateLogStream",
                "logs:CreateLogGroup"
            ],
            "Resource": [
                "arn:aws:logs:ap-northeast-2:119269236144:log-group:/aws/lambda/codepipeline-slack-dev*:*"
            ],
            "Effect": "Allow"
        },
        {
            "Action": [
                "logs:PutLogEvents"
            ],
            "Resource": [
                "arn:aws:logs:ap-northeast-2:119269236144:log-group:/aws/lambda/codepipeline-slack-dev*:*:*"
            ],
            "Effect": "Allow"
        },
        {
            "Action": [
                "codepipeline:Get*",
                "codepipeline:List*"
            ],
            "Resource": "*",
            "Effect": "Allow"
        },
        {
            "Action": [
                "codebuild:Get*"
            ],
            "Resource": "*",
            "Effect": "Allow"
        },
        {
            "Action": [
                "codedeploy:Get*"
            ],
            "Resource": "*",
            "Effect": "Allow"
        },
        {
            "Action": [
                "dynamodb:*"
            ],
            "Resource": "arn:aws:dynamodb:ap-northeast-2:119269236144:table/codepipeline-slack-integration",
            "Effect": "Allow"
        },
        {
            "Action": [
                "sqs:ReceiveMessage",
                "sqs:DeleteMessage",
                "sqs:GetQueueAttributes"
            ],
            "Resource": "*",
            "Effect": "Allow"
        },
        {
            "Action": [
                "sqs:ReceiveMessage",
                "sqs:DeleteMessage",
                "sqs:GetQueueAttributes"
            ],
            "Resource": [
                "arn:aws:sqs:ap-northeast-2:119269236144:codepipeline-slack-queue"
            ],
            "Effect": "Allow"
        }
    ]
}
EOF

  allowed_triggers = {
    CodePipelineSlackQueue = {
      principal = "sqs.amazonaws.com",
      source_arn = aws_sqs_queue.codepipeline_slack_queue.arn
    }
  }

  reserved_concurrent_executions = 1
  memory_size = 256
  timeout = 30

  tags = {
    monitor = "false"
  }
}

resource "aws_lambda_event_source_mapping" "default" {
  event_source_arn = aws_sqs_queue.codepipeline_slack_queue.arn
  function_name    = module.lambda_function.lambda_function_arn
  batch_size = 1
  enabled = true
}