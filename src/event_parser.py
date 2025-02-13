import re
import logging
import json

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def parse_sqs_message(message):
    logger.info(json.dumps(message, indent=2))
    notification = json.loads(message['Records'][0]['body'])
    return json.loads(notification['Message'])


def get_pipeline_metadata(event):
    detail = event['detail']
    pipeline_execution_id = detail['execution-id']
    pipeline_name = detail['pipeline']
    return pipeline_execution_id, pipeline_name


def is_pipeline_state_update(event):
    return event['detail-type'] == "CodePipeline Pipeline Execution State Change"


def is_pipeline_stage_state_update(event):
    return event['detail-type'] == "CodePipeline Stage Execution State Change"


def get_pipeline_stages(event):
    return event['detail']['stage']


def get_pipeline_states(event):
    return event['detail']['state']


def get_pipeline_metadata_from_codebuild(event):
    detail = event['detail']
    pipeline_name = detail['additional-information']['initiator'][13:]
    build_id = detail['build-id']
    build_project_name = detail['project-name']

    return pipeline_name, build_id, build_project_name


def is_codebuild_phases_updatable(event):
    return 'phases' in event['detail']['additional-information']


def get_codebuild_phases(event):
    return event['detail']['additional-information']['phases']


def has_phase_context(phase):
    return 'phase-context' in phase


def get_phase_context(phase):
    return phase['phase-context']


def get_phase_status(phase):
    if 'phase-status' in phase:
        return phase['phase-status']
    else:
        return 'IN_PROGRESS'


def get_phase_type(phase):
    if 'phase-type' in phase:
        return phase['phase-type']
    else:
        return None


def get_phase_duration(phase):
    if 'duration-in-seconds' in phase:
        return phase['duration-in-seconds']
    else:
        return None


def is_event_with_deployment_id(event):
    if event['source'] == 'aws.codedeploy':
        if event['detail'].get('eventName') == 'CreateDeployment':
            return True
    if event['source'] == 'aws.codepipeline' and event['detail-type'] == 'CodePipeline Action Execution State Change':
        if event['detail']['stage'] == 'Deploy' and event['detail']['state'] == 'SUCCEEDED':
            if event['detail']['execution-result']:
                return True
    return False


def get_deployment_info_from_codedeploy(event):
    deployment_id = event['detail']['responseElements'].get('deploymentId')
    app_spec = event['detail']['requestParameters']['revision']['string']['content']
    pattern = re.compile(r'TaskDefinition: [\w|:\-\/]+')
    task_def = pattern.findall(app_spec)[0].split('/')[-1]
    return deployment_id, task_def


def get_deployment_info_from_codepipeline(event):
    deployment_id = event['detail']['execution-result'].get('external-execution-id')
    pipeline_id = event['detail']['execution-id']
    return deployment_id, pipeline_id


def get_ecs_task_stopped_reason(event):
    try:
        return event['detail']['stoppedReason']
    except Exception:
        return None


def get_ecs_task_infos(event):
    try:
        resource = event['resources'][0]
        task_id = resource.split('/')[-1]
        cluster_name = resource.split('/')[-2]
        group = event['detail']['group']
        task_definition_name = event['detail']['taskDefinitionArn'].split('/')[-1]
        return cluster_name, group, task_id, task_definition_name
    except Exception as e:
        logger.exception('error while parsing event.', exc_info=True)
        return None, None, None, None


def get_ecs_container_infos(event):
    try:
        containers = event['detail']['containers']
        container_infos = []

        for container in containers:
            reason = container.get('reason', '')
            container_infos.append({
                'name': container['name'],
                'reason': reason,
            })
        return container_infos
    except Exception as e:
        logger.exception('error while parsing event.', exc_info=True)
        return None
