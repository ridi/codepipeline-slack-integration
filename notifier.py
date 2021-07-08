import logging
import json

from event_parser import (
    get_pipeline_metadata,
    get_pipeline_metadata_from_codebuild,
    is_codebuild_phases_updatable,
    get_codebuild_phases,
    is_event_with_deployment_id,
    get_deployment_info_from_codedeploy,
    get_deployment_info_from_codepipeline,
)
from slack_helper import find_slack_message_for_update
from dynamodb_helper import (
    find_or_create_item,
    update_item,
)
from message_builder import (
    MessageBuilder,
    post_message
)
from aws_client import (
    find_revision_info,
    find_pipeline_from_build,
)
from ecs_alarm import alarm_task


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def run(event, context):
    logger.info('event received.')
    logger.info(json.dumps(event, indent=2))
    if event['detail-type'] == 'AWS API Call via CloudTrail' and event['source'] == 'aws.codebuild':
        logger.info('skip CloudTrail | codebuild')
        return
    if event['source'] == "aws.codepipeline":
        process_code_pipeline(event)
    elif event['source'] == "aws.codebuild":
        process_code_build(event)
    elif event['source'] == "aws.codedeploy":
        process_code_deploy(event)
    # elif event['source'] == "aws.ecs":
        # alarm_task(event)

def process_code_pipeline(event):
    pipeline_execution_id, pipeline_name = get_pipeline_metadata(event)
    message = find_slack_message_for_update(pipeline_execution_id)
    message_builder = MessageBuilder(message, pipeline_execution_id, pipeline_name)
    message_builder.update_pipeline_message(event=event)

    if message_builder.has_revision_info_field():
        revision_info = find_revision_info(pipeline_execution_id, pipeline_name)
        message_builder.attach_revision_info(revision_info)

    if is_event_with_deployment_id(event):
        deployment_id, pipeline_id = get_deployment_info_from_codepipeline(event)
        item = find_or_create_item(deployment_id=deployment_id, pipeline_id=pipeline_id)
        if item:
            update_item(deployment_id=deployment_id, pipeline_id=pipeline_id)
            task_def = item.get('task_def')
            message_builder.update_deploy_task_definition(task_def)
        else:
            return

    post_message(message_builder=message_builder)


def process_code_build(event):
    pipeline_name, build_id, build_project_name = get_pipeline_metadata_from_codebuild(event)
    stage_name, pipeline_execution_id, action_state = find_pipeline_from_build(pipeline_name, build_id)

    if not pipeline_execution_id:
        return

    message = find_slack_message_for_update(pipeline_execution_id)
    message_builder = MessageBuilder(message, pipeline_execution_id, pipeline_name)

    if is_codebuild_phases_updatable(event):
        phases = get_codebuild_phases(event)
        message_builder.update_build_stage_info(stage_name, phases, action_state, build_project_name)

    post_message(message_builder=message_builder)


def process_code_deploy(event):
    if is_event_with_deployment_id(event):
        deployment_id, task_def = get_deployment_info_from_codedeploy(event)
        item = find_or_create_item(deployment_id=deployment_id, task_def=task_def)
        if item:
            update_item(deployment_id=deployment_id, task_def=task_def)
            pipeline_id = item.get('pipeline_id')
            message = find_slack_message_for_update(pipeline_id)
            message_builder = MessageBuilder(message, pipeline_id, "ARBITRARY_PIPELINE_NAME")
            message_builder.update_deploy_task_definition(task_def)
        else:
            return
