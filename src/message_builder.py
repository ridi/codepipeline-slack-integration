import json
import os
import logging

from event_parser import (
    get_pipeline_metadata,
    get_pipeline_stages,
    get_pipeline_states,
    is_pipeline_stage_state_update,
    is_pipeline_state_update,
    has_phase_context,
    get_phase_context,
    get_phase_status,
    get_phase_type,
    get_phase_duration,
)
from slack_helper import (
    find_channel_id,
    SLACK_CHANNEL,
    update_message,
    send_message,
)
from github_helper import (
    find_github_info
)
from aws_client import (
    find_pipeline_schema
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SLACK_IN_PROGRESS_EMOJI   = os.getenv("SLACK_IN_PROGRESS_EMOJI", ":building_contruction:")
SLACK_IN_RESUMED_EMOJI    = os.getenv("SLACK_IN_RESUMED_EMOJI", ":arrow_forward:")
SLACK_IN_STOPPED_EMOJI    = os.getenv("SLACK_IN_STOPPED_EMOJI", ":double_vertical_bar:")
SLACK_IN_SUPERSEDED_EMOJI = os.getenv("SLACK_IN_SUPERSEDED_EMOJI", ":repeat:")
GITHUB_ICON               = os.getenv("GITHUB_ICON",":github:")
REGION                    = os.getenv("AWS_REGION", "ap-northeast-2")

STATE_ICONS = {
  'CANCELED': ":no_entry:",
  'FAILED': ":x:",
  'RESUMED': SLACK_IN_RESUMED_EMOJI,
  'STARTED': SLACK_IN_PROGRESS_EMOJI,
  'STOPPED': SLACK_IN_STOPPED_EMOJI,
  'SUCCEEDED': ":white_check_mark:",
  'SUPERSEDED': SLACK_IN_SUPERSEDED_EMOJI,
}

STATE_COLORS = {
    'CANCELED': "",
    'FAILED': "danger",
    'RESUMED': "",
    'STARTED': "#9E9E9E",
    'STOPPED': "#f00",
    'STOPPING': "#f00",
    'DEFAULT': "#eee",
    'SUCCEEDED': "good",
    'SUPERSEDED': ""
}

BUILD_PHASES = {
  'SUCCEEDED': ":white_check_mark:",
  'FAILED': ":x:",
  'FAULT': "",
  'TIMED_OUT': ":stop_watch:",
  'IN_PROGRESS': SLACK_IN_PROGRESS_EMOJI,
  'STOPPED': ""
}

CODEBUILD_PHASE_DEPENDENCY = {
    'SUBMITTED': {
        'level': 0,
        'enable_progress': True
    },
    'QUEUED': {
        'level': 1,
        'enable_progress': True
    },
    'PROVISIONING': {
        'level': 2,
        'enable_progress': True
    },
    'DOWNLOAD_SOURCE': {
        'level': 3,
        'enable_progress': True
    },
    'INSTALL': {
        'level': 4,
        'enable_progress': True
    },
    'PRE_BUILD': {
        'level': 5,
        'enable_progress': True
    },
    'BUILD': {
        'level': 6,
        'enable_progress': True
    },
    'POST_BUILD': {
        'level': 7,
        'enable_progress': True
    },
    'UPLOAD_ARTIFACTS': {
        'level': 8,
        'enable_progress': True
    },
    'FINALIZING': {
        'level': 9,
        'enable_progress': False
    },
    'COMPLETED': {
        'level': 10,
        'enable_progress': False
    },
}

STAGE_STATE_ORDER = {
    "Default" : -99,

    "STARTED" : 1,

    "STOPPING" : 2,

    "STOPPED" : 3,
    "RESUMED" : 3,

    "CANCELED" : 4,
    "FAILED" : 4,
    "SUCCEEDED" : 4
}

class MessageBuilder:
    pipeline_name = None
    pipeline_execution_id = None
    fields = None
    actions = []
    message_id = None

    def __init__(self, message, pipeline_execution_id, pipeline_name):
        self.message = message
        self.pipeline_name = pipeline_name
        self.pipeline_execution_id = pipeline_execution_id

        if message:
            attachments = message['attachments'][0]
            self.fields = attachments['fields']
            self.actions = attachments.get('actions', [])
            self.message_id = message['ts']
            logger.info(f'found existing message. message id: {self.message_id}')
        else:
            self.fields = [
                {
                    "title": self.pipeline_name,
                    "value": "UNKNOWN",
                    "short": True
                 }
            ]

    def update_pipeline_message(self, event):
        if is_pipeline_state_update(event):
            self.fields[0]['value'] = get_pipeline_states(event)

        if is_pipeline_stage_state_update(event):
            self.update_stage_field(event)

            # add github info
            logger.info('PIPELINE STAGE UPDATE')
            if event.get('detail-type') == 'CodePipeline Stage Execution State Change'\
                 and get_pipeline_stages(event) == 'Source'\
                 and get_pipeline_states(event) == 'SUCCEEDED':
                logger.info('SOURCE UPDATE')
                pipeline_execution_id, pipeline_name = get_pipeline_metadata(event)
                infos = find_github_info(pipeline_execution_id, pipeline_name)
                for info in infos:
                    self.create_github_block(info)

        if self.fields[0]['value'] == 'SUCCEEDED':
            self.complete_pipeline()

    def update_stage_field(self, event):
        current_stage = get_pipeline_stages(event)
        current_state = get_pipeline_states(event)

        stages_dict = {}

        index, field_refernece = self.get_or_create_field('Stages')
        stages_string = field_refernece['value']

        if len(stages_string) > 0:
            for stage_info_string in stages_string.split('\t'):
                icon, stage_name = stage_info_string.split(" ")
                stages_dict[stage_name] = icon

        stages_progress_dict = dict()
        for stage,icon in stages_dict.items():
            for k,v in STATE_ICONS.items():
                if v == icon:
                    stages_progress_dict[stage] = k
                    break

        # prevent state going backwards
        # AWS CloudWatchEvent doesn't guarantee the event order
        if STAGE_STATE_ORDER[current_state] >= STAGE_STATE_ORDER[stages_progress_dict.get(current_stage, 'Default')]:
            stages_progress_dict[current_stage] = current_state
        stages_dict[current_stage] = STATE_ICONS[stages_progress_dict[current_stage]]

        pipeline_stage_order = find_pipeline_schema(get_pipeline_metadata(event)[1])
        field_refernece['value'] = "\t".join([f"{stages_dict[stage]} {stage}" for stage in pipeline_stage_order if stage in stages_dict])
        self.update_field(index, field_refernece)

    def create_github_block(self,infos):
        # slack strips all newllines in field.title
        text = f"{GITHUB_ICON} `{infos['repo']}` on `{infos['branch']}` by {infos['author']}"
        index, field = self.get_or_create_field(text, short=True)
        field['value'] = f"<{infos['commit_link']}|{infos['commit_message']}>"
        self.update_field(index, field)

    def update_deploy_task_definition(self, task_def):
        task_def_name = task_def.split(':')[0]
        task_def_revision = task_def.split(':')[1]
        task_def_link = f"https://{REGION}.console.aws.amazon.com/ecs/home?region={REGION}#/taskDefinitions/{task_def_name}/{task_def_revision}"

        index, field = self.get_or_create_field('Task Definition', short=True)
        field['value'] = f"<{task_def_link}|{task_def}>"
        self.update_field(index, field)



    def update_build_stage_info(self, stage_name, phases, action_states, build_project_name):
        external_execution_url = action_states['latestExecution']['externalExecutionUrl']

        if external_execution_url:
            self.get_or_create_action("Build info", external_execution_url)

        if os.getenv('SHOW_BUILD_PHASE') == 'True':
            build_field_name = MessageBuilder.create_codebuild_name_from_pipeline_stage(
                stage_name, build_project_name
            )

            index, field = self.get_or_create_field(build_field_name, short=False)
            self.create_phase_context(phases)
            field['value'] = self.complete_create_codebuild_progress_info(phases, build_field_name)
            self.update_field(index, field)

    def create_phase_context(self, phases):
        context = []
        for phase in phases:
            if has_phase_context(phase):
                phase_context = get_phase_context(phase)

                if len(phase_context) > 0 and phase_context[0] != ': ':
                    context.append(phase_context)

        if len(context) != 0:
            index, context_field = self.get_or_create_field("Build Context", short=False)
            context_field['value'] = " ".join(context)
            self.update_field(index, context_field)

    def complete_create_codebuild_progress_info(self, phases, build_field_name):
        exist_phases, exist_phase_max_level = self.create_exist_codebuild_progress_info(build_field_name)
        new_phases, new_max_level = self.create_new_codebuild_progress_info(phases)

        if exist_phase_max_level is None and new_max_level is None:
            return ""

        elif exist_phase_max_level is not None and new_max_level is not None:
            if exist_phase_max_level <= new_max_level:
                return self.create_codebuild_progress_info_message(new_phases)

            elif exist_phase_max_level > new_max_level:
                return self.create_codebuild_progress_info_message(exist_phases)

        elif exist_phase_max_level is None and new_max_level is not None:
            return self.create_codebuild_progress_info_message(new_phases)
        else:
            return self.create_codebuild_progress_info_message(exist_phases)

    def create_codebuild_progress_info_message(self, phases):
        total_message = ""
        for phase_type, phase_info_dict in phases.items():
            icon = phase_info_dict['icon']
            duration = phase_info_dict['duration']
            if not CODEBUILD_PHASE_DEPENDENCY[phase_type]['enable_progress']:
                icon = BUILD_PHASES['SUCCEEDED']

            message = f"{icon} {phase_type}"
            if duration is not None:
                message = f"{message} {duration}"

            total_message = total_message + '\n' + message

        return total_message

    def create_new_codebuild_progress_info(self, phases):
        new_phases = {}
        phase_max_level = 0
        if len(phases) == 0:
            return None, None

        for phase in phases:
            phase_status_icon = BUILD_PHASES[get_phase_status(phase)]
            phase_type = get_phase_type(phase)
            duration = get_phase_duration(phase)

            new_phases[phase_type] = {
                'icon': phase_status_icon,
                'duration': duration
            }
            phase_max_level = max(
                CODEBUILD_PHASE_DEPENDENCY[phase_type]['level'],
                phase_max_level
            )

        return new_phases, phase_max_level

    def create_exist_codebuild_progress_info(self, build_field_name):
        index, build_field = self.get_field(build_field_name)
        if build_field is None:
            return None, None
        if "value" not in build_field:
            return None, None
        if build_field["value"] == "":
            return None, None

        build_info = build_field['value']
        exist_phases = {}
        phase_max_level = 0
        for row in build_info.split('\n'):
            infos = row.strip().split(' ')
            print(row, len(infos))
            if len(infos) == 3:
                icon, phase, duration = infos
            elif len(infos) == 2:
                icon, phase = infos
                duration = None
            else:
                continue

            exist_phases[phase] = {
                'icon': icon,
                'duration': duration
            }
            phase_max_level = max(
                CODEBUILD_PHASE_DEPENDENCY[phase]['level'],
                phase_max_level
            )

        return exist_phases, phase_max_level

    def get_or_create_field(self, title, short=True):
        index, field = self.get_field(title)
        logger.info('index, field')
        logger.info(f'{index}, {field}')
        if field is not None:
            return index, field

        new_field = {
            "title": title,
            "value": "",
            "short": short
        }
        self.fields.append(new_field)
        return len(self.fields) - 1, new_field

    def get_field(self, title):
        for index, field in enumerate(self.fields):
            if field['title'] == title:
                return index, field
        return None, None

    def update_field(self, index, value):
        if index >= len(self.fields) or index < 0:
            raise ValueError(f'index out of range. input index: {index}. max length: {len(self.fields)}')

        self.fields[index] = value

    def get_or_create_action(self, name, link):
        for index, action in enumerate(self.actions):
            if action['text'] == name:
                return index, action

        action = {
            "type": "button",
            "text": name,
            "url": link
        }
        self.actions.append(action)
        return len(self.actions) - 1, self.actions[-1]

    def update_action(self, index, value):
        if index >= len(self.actions) or index < 0:
            raise ValueError(f'index out of range. input index: {index}. max length: {len(self.actions)}')

        self.actions[index] = value

    def attach_revision_info(self, revision_info):
        if 'revisionUrl' in revision_info:
            self.fields.append({
                "title": "Revision",
                "value": f"<{revision_info['revisionUrl']}|{revision_info['revisionId'][:7]}:"
                f" {revision_info['revisionSummary']}>",
                "short": True
            })
        else:
            self.fields.append({
                "title": "Revision",
                "value": revision_info['revisionSummary'],
                "short": True
            })

    def has_revision_info_field(self):
        for field in self.fields:
            if field['title'] == 'Revision':
                return True

        return False

    def color(self):
        pipeline_status = self.fields[0]['value']
        if pipeline_status in STATE_COLORS:
            return STATE_COLORS[pipeline_status]
        else:
            return STATE_COLORS['DEFAULT']

    def build_message(self):
        pipelink_link = f"https://{REGION}.console.aws.amazon.com/codesuite/codepipeline/pipelines/{self.pipeline_name}/view"
        return [
            {
                "mrkdwn_in": ["fields", "footer"],
                "fields": self.fields,
                "color": self.color(),
                "footer": f"<{pipelink_link}|{self.pipeline_execution_id}>",
                "actions": self.actions
            }
        ]

    def complete_pipeline(self):
        for index, field in enumerate(self.fields):
            if isinstance(field['value'], str):
                field['value'].replace(BUILD_PHASES['IN_PROGRESS'], BUILD_PHASES['SUCCEEDED'])
                field['value'].replace(STATE_ICONS['STARTED'], STATE_ICONS['SUCCEEDED'])

                self.fields[index] = field

    @staticmethod
    def create_codebuild_name_from_pipeline_stage(stage_name, codebuild_name):
        return f"Stage: {stage_name} | CodeBuild: {codebuild_name}"


def post_message(message_builder):
    channel_id = find_channel_id(SLACK_CHANNEL)
    message = message_builder.build_message()
    message_id = message_builder.message_id
    if message_builder.message_id is not None:
        print('update message', message_id)
        update_message(channel_id, message_builder.message_id, message)
    else:
        print('send message', message_id)
        send_message(channel_id, message)
