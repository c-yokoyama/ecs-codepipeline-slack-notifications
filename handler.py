import json
import logging
import os
import pprint
import boto3
import requests
from datetime import datetime
from base64 import b64decode
from time import sleep

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
pp = pprint.PrettyPrinter(indent=4)

CODEPIPELINE_URL = "https://{0}.console.aws.amazon.com/codesuite/"\
    "codepipeline/pipelines/{1}/view"
CODEBUILD_URL = "https://{0}.console.aws.amazon.com/codesuite/codebuild/"\
    "projects/{1}/build/{1}%3A{2}/log"
ECS_URL = "https://{0}.console.aws.amazon.com/ecs/home?region={0}#/"\
    "clusters/{1}/services/{2}/details"

ENCRYPTED_HOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
DECRYPTED_SLACK_URL = boto3.client("kms").decrypt(
    CiphertextBlob=b64decode(ENCRYPTED_HOOK_URL))["Plaintext"].decode('utf-8')

# Calors of sack attachment bar
INFO_POST_COLOR = "#0174DF"
SUCCESS_POST_COLOR = "#32cd32"
ERROR_POST_COLOR = "#dc143c"
ECS_RUN = "#ffa500"
ECS_STOP = "#808080"


def lambda_handler(event, context):
    logger.debug("Event:  " + json.dumps(event))

    region = event["region"]
    if event["source"] == "aws.codepipeline":
        parse_pipeline_details(region, event["detail"])
    elif event["source"] == "aws.codebuild":
        parse_codebuild_details(region, event["detail"])
    elif event["source"] == "aws.ecs":
        parse_ecs_details(region, event["detail"])


def post_to_slack(text, attachments):
    requests.post(DECRYPTED_SLACK_URL, data=json.dumps({
        "text": text,
        "attachments": attachments
    }))


def parse_pipeline_details(region, detail):
    pipeline_name = detail["pipeline"]

    if "stage" not in detail:
        return
    stage = detail["stage"]
    state = detail["state"]

    #  Omit notification below cases
    if stage == "Source" and state == "SUCCEEDED":
        return
    elif stage == "Build" and state == "STARTED":
        return
    elif stage == "Deploy" and state == "STARTED":
        return

    codepipeline = boto3.client("codepipeline")

    # Get commit hash and some info of source repository
    exec_detail = codepipeline.get_pipeline_execution(
        pipelineName=pipeline_name, pipelineExecutionId=detail["execution-id"])

    fields = [
        {
            "title": "Stage",
            "value": stage,
            "short": "true"
        },
        {
            "title": "State",
            "value": state,
            "short": "true"
        }
    ]

    pipeline = codepipeline.get_pipeline(name=pipeline_name)
    logging.debug("debug>pipeline: " + str(pipeline))
    branch = pipeline["pipeline"]["stages"][0]["actions"][0]["configuration"]["Branch"]
    fields.append(
        {
            "title": "BranchName",
            "value": branch
        }
    )

    artifact_rev = exec_detail["pipelineExecution"]["artifactRevisions"]
    if artifact_rev:
        commit_hash = artifact_rev[0]["revisionId"]
        fields.extend([
            {
                "title": "Revision Summary",
                "value": artifact_rev[0]["revisionSummary"] +
                " : `" + commit_hash[:8] + "`"
            },
            {
                "title": "Revision URL",
                "value": artifact_rev[0]["revisionUrl"]
            }
        ])

    color = ERROR_POST_COLOR
    if state == "STARTED":
        color = INFO_POST_COLOR
    elif state == "SUCCEEDED":
        color = SUCCESS_POST_COLOR

    now_unix_time = datetime.now().strftime('%s')

    attachments = [
        {
            "fallback": "AWS CodePipeline notification attachment",
            "color": color,
            "title": "AWS CodePipeline: " + pipeline_name,
            "title_link": CODEPIPELINE_URL.format(region, pipeline_name),
            "fields": fields,
            "footer": "send by ecs-codepipeline-notifier",
            "ts": now_unix_time
        }
    ]

    post_to_slack("", attachments)


def parse_codebuild_details(region, detail):
    project_name = detail["project-name"]
    build_id = detail["build-id"].split(":")[-1]
    state = detail["build-status"]

    if state == "SUCCEEDED":
        return

    fields = [
        {
            "title": "Build Status",
            "value": state,
            "short": "true"
        },
        {
            "title": "Build ID",
            "value": build_id,
            "short": "true"
        },
    ]

    # WorkAruond the case this notification is posted before Source stage
    sleep(5)

    color = ERROR_POST_COLOR
    if state == "IN_PROGRESS":
        color = INFO_POST_COLOR

    now_unix_time = datetime.now().strftime('%s')

    attachments = [
        {
            "fallback": "AWS CodeBuild notification attachment",
            "color": color,
            "title": "AWS CodeBuild: " +
            project_name + ", Build Log (Click here)",
            "title_link": CODEBUILD_URL.format(region, project_name, build_id),
            "fields": fields,
            "footer": "send by ecs-codepipeline-notifier",
            "ts": now_unix_time
        }
    ]

    post_to_slack("", attachments)


def parse_ecs_details(region, detail):
    service_name = detail["group"].split(":")[-1]
    cluster_name = detail["clusterArn"].split("/")[-1]
    last_status = detail["lastStatus"]

    # Omit below case
    if last_status in ["DEPROVISIONING", "DEACTIVATING", "ACTIVATING", "PROVISIONING"]:
        return

    desired_status = detail["desiredStatus"]
    task_difinition = detail["taskDefinitionArn"].split("/")[-1]

    fields = [
        {
            "title": "Last Status",
            "value": last_status,
            "short": "true"
        },
        {
            "title": "Desired Status",
            "value": desired_status,
            "short": "true"
        },
        {
            "title": "ECS Task Definition",
            "value": task_difinition
        }
    ]

    color = ECS_RUN
    if desired_status == "STOPPED":
        color = ECS_STOP

    now_unix_time = datetime.now().strftime('%s')

    attachments = [
        {
            "fallback": "ECS notification attachment",
            "color": color,
            "title": "Amazon ECS: " + cluster_name + "/" + service_name,
            "title_link": ECS_URL.format(region, cluster_name, service_name),
            "fields": fields,
            "footer": "send by ecs-codepipeline-notifier",
            "ts": now_unix_time
        }
    ]

    post_to_slack("", attachments)
