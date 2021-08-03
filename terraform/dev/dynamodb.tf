resource "aws_dynamodb_table" "default" {
  name           = "codepipeline-slack-integration"
  billing_mode   = "PROVISIONED"
  read_capacity  = 5
  write_capacity = 5
  hash_key       = "deployment_id"

  attribute {
    name = "deployment_id"
    type = "S"
  }

  tags = {
    Name = "codepipeline-slack-integration"
  }
}
