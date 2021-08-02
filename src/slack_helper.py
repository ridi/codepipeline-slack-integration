import os
import json
import requests as re
import logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "builds_test")
SLACK_BOT_NAME = os.getenv("SLACK_BOT_NAME", "PipelineBot")
SLACK_BOT_ICON = os.getenv("SLACK_BOT_ICON", ":robot_face:")
SLACK_CHANNEL_ID = os.getenv('SLACK_CHANNEL_OVERRIDE_CHANNEL_ID')

def find_slack_message_for_update(pipeline_execution_id):
    channel_id = find_channel_id(SLACK_CHANNEL)
    slack_bot_info = slack_api_get(url='auth.test')
    slack_bot_id = slack_bot_info['user_id']
    slack_messages = get_slack_messages_from_channel(channel_id=channel_id)

    for message in slack_messages:
        if message.get('user', '') != slack_bot_id:
            continue

        attachments = message.get('attachments', [])
        for attachment in attachments:
            if 'footer' not in attachment:
                continue
            if attachment['footer'].split('|')[-1].split('>')[0] == pipeline_execution_id:
                return message

    return None


def find_channel_id(channel_name):
    # slack api does not provide effcient search for channel(conversation) id by channel name
    # an option to override the api call if channel_id is provided
    # slack sometimes have issue with channel id changing randomly
    # use with caution
    # ALSO there's a ratelimit to this api
    if SLACK_CHANNEL_ID:
        return SLACK_CHANNEL_ID

    # 최신 메세지가 가장 위쪽에 있게 줌
    res = slack_api_get(url='conversations.list', params={'exclude_archived':1, 'limit':1000})

    if 'error' in res:
        if not isinstance(res['error'], str):
            err_message = ''
        else:
            err_message = res['error']
        raise ValueError(f'can not read channel list. error message from slack:{err_message}')

    channels = res['channels']

    for channel in channels:
        if channel['name'] == channel_name:
            return channel['id']

    raise ValueError(f'can not find channel. channel name:{channel_name}')


def get_slack_messages_from_channel(channel_id):
    res = slack_api_get(url='conversations.history', params={'channel':channel_id, 'limit':10})

    if 'error' in res:
        if not isinstance(res['error'], str):
            err_message = ''
        else:
            err_message = res['error']
        raise ValueError(f'can not read channel list. error message from slack:{err_message}')

    return res['messages']


def update_message(channel_id, message_id, attachments):
    res = slack_api_post(url='chat.update', data={
        'channel':channel_id,
        'ts':message_id,
        'username':SLACK_BOT_NAME,
        'attachments':attachments
    })

    if 'error' in res:
        if not isinstance(res['error'], str):
            err_message = ''
        else:
            err_message = res['error']
        raise ValueError(f'can update message. error message from slack:{err_message}')

    return res


def send_message(channel_id, attachments):
    res = slack_api_post(url='chat.postMessage', data={
        'channel':channel_id,
        'username':SLACK_BOT_NAME,
        'attachments':attachments
    })

    if 'error' in res:
        if not isinstance(res['error'], str):
            err_message = ''
        else:
            err_message = res['error']
        raise ValueError(f'can update message. error message from slack:{err_message}')

    return res


HEADERS = {'Authorization' : f'Bearer {SLACK_BOT_TOKEN}', 'Content-Type': 'application/json; charset=utf-8'}
def slack_api_get(url='', params={}):
    r = re.get('https://slack.com/api/'+url, params=params, headers=HEADERS)
    r_json = json.loads(r.text)
    return r_json


def slack_api_post(url='', data=None):
    r = re.post('https://slack.com/api/'+url, headers=HEADERS, data=json.dumps(data))
    r_json = json.loads(r.text)
    return r_json
