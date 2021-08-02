import os
import json
from urllib.parse import urlparse, parse_qs
import boto3
import requests as re
import aws_client
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

GITHUB_ACCESS_TOKEN = os.getenv('GITHUB_ACCESS_TOKEN')


def find_github_info(pipeline_execution_id, pipeline_name):
    infos = []

    # action_name, repo, branchname
    pipeline = aws_client.client.get_pipeline(name=pipeline_name)
    stages = pipeline.get('pipeline').get('stages')
    source_stage = [x for x in stages if x.get('name') == 'Source'][0]
    for action in source_stage.get('actions'):
        infos.append({'name': action['name'], 'repo': action['configuration']['FullRepositoryId'], 'branch': action['configuration']['BranchName']})

    # commit_message, commit_link
    pipeline_execution = aws_client.client.get_pipeline_execution(pipelineName=pipeline_name, pipelineExecutionId=pipeline_execution_id)
    revisions = pipeline_execution.get('pipelineExecution').get('artifactRevisions')
    for revision in revisions:
        info = [x for x in infos if x['name'] == revision['name']][0]
        commit_message = json.loads(revision['revisionSummary'])['CommitMessage']
        info['commit_message'] = commit_message.split('\n')[0]

        query = parse_qs(urlparse(revision['revisionUrl']).query)
        info['commit_link'] = f"https://github.com/{query.get('FullRepositoryId')[0]}/commit/{query.get('Commit')[0]}"

    # author
    for info in infos:
        sha = info['commit_link'].split('/')[-1]
        url = f"/repos/{info['repo']}/commits/{sha}"
        author = github_api(url).get('commit').get('author').get('name')
        info['author'] = author

    return infos

def github_api(url):
    r = re.get('https://api.github.com'+url, auth=('token',GITHUB_ACCESS_TOKEN))
    r_json = json.loads(r.text)
    return r_json
