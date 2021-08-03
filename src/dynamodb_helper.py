import os
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
table = os.getenv('DYNAMODB_TABLE')


def find_or_create_item(deployment_id, *, pipeline_id=None, task_def=None):
    item = table.get_item(Key={'deployment_id': deployment_id}).get('Item')
    if item:
        return item
    else:
        table.put_item(Item={'deployment_id':deployment_id, 'pipeline_id':pipeline_id, 'task_def':task_def})


def update_item(*, deployment_id, pipeline_id=None, task_def=None):
    expression = 'SET'
    expression_attributes = dict()
    if pipeline_id != None:
        expression += f' pipeline_id = :p'
        expression_attributes[':p'] = pipeline_id
    if task_def != None:
        expression += f', task_def = :t'
        expression_attributes[':t'] = task_def

    table.update_item(
        Key={'deployment_id':deployment_id},
        UpdateExpression=expression,
        ExpressionAttributeValues=expression_attributes)
