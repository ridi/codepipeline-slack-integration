terraform {
  backend "remote" {
    hostname     = "app.terraform.io"
    organization = "ridi"

    workspaces {
      name = "ridi-prod-codepipline-slack-integration"
    }
  }
  required_version = ">= 0.14.8"
  required_providers {
    aws = ">= 3.32.0"
  }
}

provider "aws" {
  profile = "default"
  region  = "ap-northeast-2"
}

resource "aws_iam_role" "sns_success_iam" {
  name = "SNSSuccessFeedback"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
        {
            Effect = "Allow",
            Action = [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:PutMetricFilter",
                "logs:PutRetentionPolicy"
            ],
            Resource: [
                "*"
            ]
        }
    ]
  })
}

resource "aws_iam_role" "sns_failure_iam" {
  name = "SNSFailureFeedback"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
        {
            Effect = "Allow",
            Action = [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:PutMetricFilter",
                "logs:PutRetentionPolicy"
            ],
            Resource: [
                "*"
            ]
        }
    ]
  })
}

resource "aws_sns_topic" "codepipeline_events_sns" {
  name = "codepipeline_events_sns"

  sqs_success_feedback_sample_rate = 100
  sqs_success_feedback_role_arn    = aws_iam_role.sns_success_iam.arn
  sqs_failure_feedback_role_arn    = aws_iam_role.sns_failure_iam.arn

  delivery_policy = <<EOF
{
  "http": {
    "defaultHealthyRetryPolicy": {
      "numRetries": 3,
      "numNoDelayRetries": 0,
      "minDelayTarget": 20,
      "maxDelayTarget": 20,
      "numMinDelayRetries": 0,
      "numMaxDelayRetries": 0,
      "backoffFunction": "linear"
    },
    "disableSubscriptionOverrides": false
  }
}
EOF
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "sns_topic_policy" {
  statement {
    sid = "1"
    principals {
      type        = "AWS"
      identifiers = [ data.aws_caller_identity.current.account_id ]
    }
    actions = [
      "SNS:Publish",
      "SNS:RemovePermission",
      "SNS:SetTopicAttributes",
      "SNS:DeleteTopic",
      "SNS:ListSubscriptionsByTopic",
      "SNS:GetTopicAttributes",
      "SNS:Receive",
      "SNS:AddPermission",
      "SNS:Subscribe"
    ]
    resources = [ aws_sns_topic.codepipeline_events_sns.arn ]
  }

  statement {
    sid = "2"
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    actions = [
      "SNS:Publish"
    ]
    resources = [ aws_sns_topic.codepipeline_events_sns.arn ]
  }
}

resource "aws_sns_topic_policy" "default" {
  arn = aws_sns_topic.codepipeline_events_sns.arn
  policy = data.aws_iam_policy_document.sns_topic_policy.json
}

resource "aws_sqs_queue" "codepipeline_slack_dlq" {
  name                       = "codepipeline-slack-dlq"
  visibility_timeout_seconds = 180
  message_retention_seconds  = 345600
  max_message_size           = 262144
  delay_seconds              = 0
  receive_wait_time_seconds  = 0
}

resource "aws_sqs_queue" "codepipeline_slack_queue" {
  name                       = "codepipeline-slack-queue"
  visibility_timeout_seconds = 180
  message_retention_seconds  = 345600
  max_message_size           = 262144
  delay_seconds              = 0
  receive_wait_time_seconds  = 0

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.codepipeline_slack_dlq.arn
    maxReceiveCount     = 15
  })
}

data "aws_iam_policy_document" "sqs_policy" {
  statement {
    principals {
      type        = "Service"
      identifiers = [ "sns.amazonaws.com" ]
    }
    actions = [
      "sqs:SendMessage"
    ]
    resources = [ aws_sqs_queue.codepipeline_slack_queue.arn ]
    condition {
      test = "ArnEquals"
      variable = "aws:SourceArn"
      values = [ aws_sns_topic.codepipeline_events_sns.arn ]
    }
  }
}

resource "aws_sqs_queue_policy" "codepipeline_slack_dlq_policy" {
  queue_url = aws_sqs_queue.codepipeline_slack_dlq.id
  policy = data.aws_iam_policy_document.sqs_policy.json
}

resource "aws_sqs_queue_policy" "codepipeline_slack_queue_policy" {
  queue_url = aws_sqs_queue.codepipeline_slack_queue.id
  policy = data.aws_iam_policy_document.sqs_policy.json
}

resource "aws_sns_topic_subscription" "user_updates_sqs_target" {
  topic_arn = aws_sns_topic.codepipeline_events_sns.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.codepipeline_slack_queue.arn
}

resource "aws_cloudwatch_event_rule" "codepipeline_event_rule" {
  name = "codepipeline_event_rule"

  event_pattern = <<EOF
{
  "source": [
    "aws.codepipeline"
  ],
  "detail-type": [
    "CodePipeline Pipeline Execution State Change",
    "CodePipeline Stage Execution State Change",
    "CodePipeline Action Execution State Change"
  ]
}
EOF
}

resource "aws_cloudwatch_event_rule" "codedeploy_event_rule" {
  name = "codedeploy_event_rule"

  event_pattern = <<EOF
{
  "source": [
    "aws.codedeploy"
  ],
  "detail-type": [
    "AWS API Call via CloudTrail"
  ],
  "detail": {
    "eventName": [
      "CreateDeployment"
    ]
  }
}
EOF
}

resource "aws_cloudwatch_event_target" "codepipeline_event_target" {
  rule      = aws_cloudwatch_event_rule.codepipeline_event_rule.name
  target_id = "codepipeline_event_target"
  arn       = aws_sns_topic.codepipeline_events_sns.arn
}

resource "aws_cloudwatch_event_target" "codedeploy_event_target" {
  rule      = aws_cloudwatch_event_rule.codedeploy_event_rule.name
  target_id = "codedeploy_event_target"
  arn       = aws_sns_topic.codepipeline_events_sns.arn
}
