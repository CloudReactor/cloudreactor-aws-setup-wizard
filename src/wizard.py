import argparse
from datetime import datetime
import json
import os
import logging
import random
import re
import string
import time

import jsonpickle
import urllib3

import boto3
from botocore.exceptions import ClientError

import questionary

DEFAULT_LOG_LEVEL = 'ERROR'
SAVED_STATE_FILENAME = 'saved_settings.json'
DEFAULT_PREFIX = ' (Default)'
KEY_LENGTH = 32
DEFAULT_RUN_ENVIRONMENT_NAME = 'staging'
CREATE_NEW_ECS_CLUSTER_CHOICE = 'Create new ECS cluster ...'
ECS_CLUSTER_NAME_REGEX = re.compile(r'[a-zA-Z][-a-zA-Z0-9]{0,254}')
DEFAULT_ECS_CLUSTER_NAME = 'staging'
CLOUDFORMATION_TEMPLATE_URL = 'https://cloudreactor-customer-setup.s3-us-west-2.amazonaws.com/cloudreactor-aws-role-template.json'
CLOUDFORMATION_STACK_NAME_REGEX = re.compile(r'[a-zA-Z][-a-zA-Z0-9]{0,127}')
CLOUDFORMATION_IN_PROGRESS_STATUSES = set([
    'CREATE_IN_PROGRESS', 'UPDATE_IN_PROGRESS',
    'UPDATE_COMPLETE_CLEANUP_IN_PROGRESS',
    'IMPORT_IN_PROGRESS'
])
CLOUDFORMATION_SUCCESSFUL_STATUSES = set([
  'CREATE_COMPLETE', 'UPDATE_COMPLETE', 'IMPORT_COMPLETE'
])

CLOUDREACTOR_API_BASE_URL = os.environ.get('CLOUDREACTOR_API_BASE_URL', 'https://api.cloudreactor.io')

AWS_REGIONS = [
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "us-gov-east-1",
    "us-gov-west-1",
    "ap-west-1",
    "ap-south-1",
    "ap-northeast-1",
    "ap-northeast-2",
    "ap-northeast-3",
    "eu-central-1",
    "eu-west-1",
    "eu-west-2",
    "eu-west-3",
    "eu-north-1",
    "me-south-1",
    "sa-east-1",
    "ca-central-1",
    "cn-north-1",
    "cn-northwest-1",
]

DEFAULT_AWS_REGION = 'us-west-2'


def print_banner():
    with open('banner.txt') as f:
        print(f.read())


class Wizard(object):
    MODE_INTERVIEW = 'interview'
    MODE_EDIT = 'edit'

    NUMBER_TO_PROPERTY = {
        '1': ['api_key', 'CloudReactor API key'],
        '2': ['run_environment_name', 'CloudReactor Run Environment'],
        '3': ['aws_region', 'AWS region'],
        '4': ['aws_access_key', 'AWS access key'],
        '5': ['aws_secret_key', 'AWS secret key'],
        '6': ['cluster_arn', 'AWS ECS Cluster'],
        '7': ['stack_name', 'CloudFormation stack name']
    }

    def __init__(self, deployment: str):
        self.deployment_environment = deployment
        self.run_environment_name = None
        self.api_key = None
        self.existing_run_environments = None
        self.aws_access_key = None
        self.aws_secret_key = None
        self.aws_region = None
        self.aws_account_id = None
        self.available_cluster_arns = None
        self.cluster_arn = None
        self.stack_name = None
        self.external_id = None
        self.workflow_starter_access_key = None
        self.uploaded_stack_id = None
        self.assumable_role_arn = None
        self.task_execution_role_arn = None
        self.workflow_starter_arn = None
        self.stack_upload_started_at = None
        self.stack_upload_succeeded = None
        self.stack_upload_finished_at = None

        self.mode = Wizard.MODE_INTERVIEW

    def print_menu(self):
        for choice in self.make_property_choices():
            print(choice)

    def make_property_choices(self):
        choices = []
        property_count = len(Wizard.NUMBER_TO_PROPERTY)
        for i in range(property_count):
            n = i + 1
            arr = Wizard.NUMBER_TO_PROPERTY[str(n)]
            choices.append(f"{n}. {arr[1]}: {str(self.__dict__[arr[0]] or '(Not Set)')}")
        return choices

    def run(self):
        finished = False
        while not finished:
            if self.uploaded_stack_id:
                self.wait_for_stack_upload()

            self.print_menu()

            if self.mode == Wizard.MODE_INTERVIEW:
                rv = questionary.confirm("Continue step-by-step interview? (n switches to editing settings)").ask()
                if not rv:
                    self.mode = Wizard.MODE_EDIT
                    self.save()

            proceed = True

            while proceed:
                if wizard.mode == Wizard.MODE_INTERVIEW:
                    proceed = self.interview()
                else:
                    proceed = self.edit()



    def interview(self):
        property_count = len(Wizard.NUMBER_TO_PROPERTY)
        for i in range(property_count):
            n = i + 1
            arr = Wizard.NUMBER_TO_PROPERTY[str(n)]

            if self.__dict__[arr[0]] is None:
                self.edit_property(n)

        rv = questionary.confirm("All settings have been entered. Proceed with CloudReactor setup?").ask()

        if rv:
            self.start_cloudformation_template_upload()

        return False

    def edit(self):
        choices = self.make_property_choices()

        n = len(choices)

        choices.append(f"{n + 1}. Back to interview")
        choices.append(f"{n + 2}. Quit")

        selected = questionary.select(
            "Which setting do you want to edit?",
            choices=choices).ask()

        dot_index = selected.find('.')
        number = int(selected[:dot_index])

        if number == n + 1:
            self.mode = Wizard.MODE_INTERVIEW
            return True
        elif number == n + 2:
            exit(0)

        self.edit_property(number)
        return True

    def edit_property(self, n):
        arr = Wizard.NUMBER_TO_PROPERTY[str(n)]
        p = arr[0]

        if p == 'api_key':
            self.ask_for_api_key()
        elif p == 'run_environment_name':
            self.ask_for_run_environment_name()
        elif p == 'aws_access_key':
            self.ask_for_aws_access_key()
        elif p == 'aws_secret_key':
            self.ask_for_aws_secret_key()
        elif p == 'aws_region':
            self.ask_for_aws_region()
        elif p == 'cluster_arn':
            self.ask_for_ecs_cluster_arn()
        elif p == 'stack_name':
            self.ask_for_stack_name()
        else:
            print(f"{n} is not a valid choice. Please try another choice. [{p}]")

    def ask_for_api_key(self):
        q = "What is your CloudReactor API key?"

        old_api_key = self.api_key
        if old_api_key:
            q += f" [{old_api_key}]"

        self.api_key = questionary.text(q).ask() or old_api_key

        if not self.api_key:
            print("Skipping CloudReactor API key for now.")
            self.existing_run_environments = None
            self.save()
            return

        if old_api_key != self.api_key:
            self.existing_run_environments = None

        print()

        response_ok = False
        response_status = None
        response_body = None

        try:
            http = urllib3.PoolManager()
            r = http.request('GET', CLOUDREACTOR_API_BASE_URL + '/api/v1/run_environments/',
                             headers={
                                 'Authorization': f"Token {self.api_key}",
                                 'Accept': 'application/json'
                             }, timeout=10.0)
            #r = http.request('GET', 'http://httpbin.org/ip')

            response_status = r.status;

            response_body = r.data.decode('utf-8')
            page = json.loads(response_body)

            response_ok = response_status == 200
        except urllib3.exceptions.HTTPError as http_error:
            print(f"An error communicating with cloudreactor.io occurred: {http_error}")

        if response_ok:
            self.existing_run_environments = page['results']

            if len(self.existing_run_environments) == 0:
                print('No current Run Environments found. Please create a new one.')
            else:
                print(f"There are currently {page['count']} Run Environments in your organization:")

                for run_environment in self.existing_run_environments:
                    print(run_environment['name'])

            print('Your CloudReactor API key is valid.')

            self.save()
        else:
            print(f"The CloudReactor API key '{self.api_key}' is not valid. Please check that it is correct.")

            if response_body:
                print(f"Got response status {response_status} and response body: {response_body} from the server")
            else:
                print(f"Got response status {response_status} from the server")

            self.api_key = None

        print()

    def ask_for_run_environment_name(self):
        q = 'What do you want to name your Run Environment? Common names are "staging" or "production".'

        default_run_environment_name = self.run_environment_name or self.make_default_run_environment_name()

        if default_run_environment_name:
            q += f" [{default_run_environment_name}]"

        self.run_environment_name = questionary.text(q).ask() or default_run_environment_name

        if self.run_environment_name:
            print(f"Using Run Environment '{self.run_environment_name}'.\n")
        else:
            print("Skipping Run Environment for now.\n")

        # TODO: Validate if it exists already

        self.save()

    def make_default_run_environment_name(self):
        if self.cluster_arn:
            name = self.cluster_arn
            slash_index = name.rfind('/')
            if slash_index >= 0:
                name = name[(slash_index + 1):]
            return re.sub(r'[^A-Za-z-]+', '', name) or DEFAULT_RUN_ENVIRONMENT_NAME
        return DEFAULT_RUN_ENVIRONMENT_NAME

    def ask_for_aws_region(self):
        old_aws_region = self.aws_region
        default_aws_region = old_aws_region or os.environ.get('AWS_REGION') or \
                             os.environ.get('AWS_DEFAULT_REGION') or DEFAULT_AWS_REGION

        self.aws_region = questionary.select(f"Which AWS region will you run ECS tasks?",
            choices=[default_aws_region + DEFAULT_PREFIX] + AWS_REGIONS).ask().replace(
            DEFAULT_PREFIX, '')

        print(f"Using AWS region {wizard.aws_region}.")

        if old_aws_region != self.aws_region:
            self.clear_aws_state()

        self.save()

    def ask_for_aws_access_key(self):
        old_aws_access_key = self.aws_access_key
        q = 'What AWS access key do you want to use. Type "none" to use the default permissions on this machine.'

        if old_aws_access_key:
            q += f" [{old_aws_access_key}]"

        self.aws_access_key = questionary.text(q).ask() or old_aws_access_key

        if old_aws_access_key != self.aws_access_key:
            self.clear_aws_state()

        self.validate_aws_access()

    def ask_for_aws_secret_key(self):
        old_aws_secret_key = self.aws_secret_key
        q = 'What AWS secret key do you want to use. Type "none" to use the default permissions on this machine.'

        if old_aws_secret_key:
            q += f" [{old_aws_secret_key}]"

        self.aws_secret_key = questionary.text(q).ask() or old_aws_secret_key

        if self.aws_secret_key != self.aws_access_key:
            self.clear_aws_state()

        self.validate_aws_access()

    def ask_for_ecs_cluster_arn(self):
        if not self.aws_region:
            print("You must set the AWS region before selecting an ECS cluster.\n")
            return None

        ecs_client = self.make_boto_client('ecs')

        if ecs_client is None:
            print("You must set your AWS credentials before selecting an ECS cluster.\n")
            return None

        self.available_cluster_arns = None
        try:
            resp = ecs_client.list_clusters(maxResults=100)
            self.available_cluster_arns = resp['clusterArns']
            self.save()
        except Exception as ex:
            logging.warning("Can't list clusters", exc_info=True)

        if (self.available_cluster_arns is None) or (len(self.available_cluster_arns) == 0):
            if len(self.available_cluster_arns) == 0:
                rv = questionary.confirm(f"No ECS clusters found in region {self.aws_region}. Do you want to create one?").ask()

                if rv:
                    return self.create_cluster(ecs_client)

            self.cluster_arn = None
            self.save()
            return None

        choices = self.available_cluster_arns + [CREATE_NEW_ECS_CLUSTER_CHOICE]

        selection = questionary.select(
            "Which ECS cluster do you want to use to run your tasks?",
            choices=choices).ask()

        if selection == CREATE_NEW_ECS_CLUSTER_CHOICE:
            return self.create_cluster(ecs_client)
        else:
            self.cluster_arn = selection

        print(f"Using ECS cluster '{self.cluster_arn}'.\n")
        self.save()
        return self.cluster_arn

    def ask_for_stack_name(self):
        default_stack_name = self.stack_name or self.make_default_stack_name()

        good_stack_name = False
        while not good_stack_name:
            self.stack_name = questionary.text(
                f"What do you want to name the CloudFormation stack? [{default_stack_name}]").ask() or default_stack_name

            if self.stack_name is None:
                print("Skipping stack name for now.\n")
                return

            if CLOUDFORMATION_STACK_NAME_REGEX.fullmatch(self.stack_name) is None:
                print(f"'{self.stack_name}' is not a valid CloudFormation stack name. Stack names can only contain alphanumeric characters and dashes, no underscores.")
                self.stack_name = None
            else:
                good_stack_name = True

        print(f"Stack will be named '{self.stack_name}'.\n")

        self.save()
        return self.stack_name

    def make_default_stack_name(self):
        name = 'CloudReactor'

        if self.deployment_environment:
            name += f"_{deployment_environment}"

        return name

    def save(self):
        with open(SAVED_STATE_FILENAME, 'w') as f:
            f.write(jsonpickle.encode(self))

    def validate_aws_access(self):
        sts = None
        try:
            sts = self.make_boto_client('sts')
        except Exception as ex:
            logging.warning("Failed to validate AWS credentials", exc_info=True)
            print("The AWS access key / secret key pair was not valid. Please check them and try again.\n")

        if sts is None:
            self.aws_account_id = None
            self.save()
            return None

        try:
            caller_id = sts.get_caller_identity()
            self.aws_account_id = caller_id['Account']
            print(f"Your AWS credentials for AWS account {self.aws_account_id} are valid.\n")
        except Exception as ex:
            logging.warning("Failed to get caller identity from AWS", exc_info=True)
            print("Failed to fetch your AWS user info. Please check your AWS credentials and try again.\n")
            self.aws_account_id = None

        self.save()
        return self.aws_account_id

    def create_cluster(self, ecs_client=None):
        if ecs_client is None:
            ecs_client = self.make_boto_client('ecs')

        if ecs_client is None:
            print("You must set your AWS credentials before creating an ECS cluster.\n")
            return None

        default_cluster_name = self.make_default_cluster_name()

        good_cluster_name = False
        while not good_cluster_name:
            cluster_name = questionary.text(
                f"What do you want to name the ECS cluster? [{default_cluster_name}]").ask() or default_cluster_name

            if cluster_name is None:
                print("Skipping ECS cluster creation.\n")
                return None

            if ECS_CLUSTER_NAME_REGEX.fullmatch(cluster_name) is None:
                print(
                    f"'{cluster_name}' is not a valid ECS cluster name. cluster names can only contain alphanumeric characters and dashes, no underscores.")
                cluster_name = None
            else:
                good_cluster_name = True

        print(f"Creating ECS cluster '{cluster_name}' ...")

        try:
            resp = ecs_client.create_cluster(
                clusterName=cluster_name,
                capacityProviders=[
                    'FARGATE', 'FARGATE_SPOT'
                ])

            self.cluster_arn = resp['cluster']['clusterArn']
            print(f"Successfully created ECS cluster {self.cluster_arn} in region {self.aws_region}.\n")
            self.save()
        except Exception as ex:
            logging.warning("Failed to create ECS cluster.")
            print(f"Failed to create ECS cluster: {ex}")
            return None

    def make_default_cluster_name(self):
        if self.run_environment_name:
            return re.sub(r'[^A-Za-z-]+', '', self.run_environment_name) or DEFAULT_ECS_CLUSTER_NAME
        return DEFAULT_ECS_CLUSTER_NAME

    def start_cloudformation_template_upload(self):
        cf_client = self.make_boto_client('cloudformation')

        if not cf_client:
            print("You must set your AWS credentials uploading a CloudFormation template.\n")
            return None

        self.external_id = self.generate_random_key()
        self.workflow_starter_access_key = self.generate_random_key()
        self.stack_upload_started_at = datetime.now()

        try:
            resp = cf_client.create_stack(
                StackName=self.stack_name,
                TemplateURL=CLOUDFORMATION_TEMPLATE_URL,
                Parameters=[
                    {
                        'ParameterKey': 'ExternalID',
                        'ParameterValue': self.external_id,
                        'UsePreviousValue': False,
                    },
                    {
                        'ParameterKey': 'WorkflowStarterAccessKey',
                        'ParameterValue': self.workflow_starter_access_key,
                        'UsePreviousValue': False,
                    }
                ],
                Capabilities=[
                    'CAPABILITY_NAMED_IAM'
                ]
            )

            self.uploaded_stack_id = resp['StackId']
        except Exception as ex:
            logging.warning("Failed to upload stack", exc_info=True)
            print(f"Failed to upload stack: {ex}")

            exception_str = str(ex)

            if exception_str.find('AlreadyExistsException'):
                rv = questionary.confirm(f"That stack already exists. Delete it?").ask()

                if rv:
                    self.delete_stack(cf_client)

            self.clear_stack_upload_state()
            return None

        self.save()

        print(f"Started CloudFormation template upload for stack '{self.stack_name}', stack ID is {self.uploaded_stack_id}.")
        return self.uploaded_stack_id

    def wait_for_stack_upload(self):
        if not self.uploaded_stack_id:
            logging.error("wait_for_stack_upload() called but, but no stack ID was saved.")
            return False

        cf_client = self.make_boto_client('cloudformation')
        done = False

        while not done:
            resp = None
            try:
                resp = cf_client.describe_stacks(
                    StackName=self.uploaded_stack_id
                )
            except Exception as ex:
                logging.warning("Can't describe CloudFormation stacks, re-creating client ...")
                time.sleep(10)
                cf_client = self.make_boto_client('cloudformation')

            if resp:
                stacks = resp['Stacks']

                if len(stacks) == 0:
                    print(f"CloudFormation stack '{self.stack_name}' was deleted, please check your settings and try again.\n")
                    self.uploaded_stack_id = None
                    self.save()
                    return False

                stack = stacks[0]
                status = stack['StackStatus']

                if status in CLOUDFORMATION_IN_PROGRESS_STATUSES:
                    print(f"CloudFormation stack upload is still in progress ({status}). Waiting 10 seconds before checking again ...")
                    time.sleep(10)
                elif status in CLOUDFORMATION_SUCCESSFUL_STATUSES:
                    self.stack_upload_finished_at = datetime.now()

                    outputs = stack['Outputs'] or []

                    for output in outputs:
                        output_key = output['OutputKey']
                        output_value = output['OutputValue']
                        if output_key == 'CloudreactorRoleARN':
                            self.assumable_role_arn = output_value
                        elif output_key == 'TaskExecutionRoleARN':
                            self.task_execution_role_arn = output_value
                        elif output_key == 'WorkflowStarterARN':
                            self.workflow_starter_arn = output_value
                        else:
                            logging.warning(f"Got unknown output '{output_key}' with value '{output_value}'.")

                    if self.assumable_role_arn and self.task_execution_role_arn and self.workflow_starter_arn:
                        self.stack_upload_succeeded = True
                        self.save()
                        print(f"CloudFormation stack upload was successful.")
                        return True

                    print('Something was missing from the stack output. Please contact support@cloudreactor.io for help.\n')
                    self.stack_upload_succeeded = False
                    self.save()
                    return False
                else:
                    self.stack_upload_finished_at = datetime.now()
                    self.stack_upload_succeeded = False
                    self.save()

                    print(f"CloudFormation stack upload failed with status '{status}' and reason '{stack['StackStatusReason']}'.")
                    rv = questionary.confirm('Do you want to delete the stack and try again?').ask()
                    if rv:
                        self.delete_stack(cf_client)
                    return False

    def delete_stack(self, cf_client=None):
        stack_id = self.uploaded_stack_id or self.stack_name
        if not stack_id:
            print("No CloudFormation stack found to delete.")
            return

        if cf_client is None:
            cf_client = self.make_boto_client('cloudformation')

        if cf_client is None:
            print("AWS authentication is not working, can't delete CloudFormation stack.\n")
            return

        try:
            cf_client.delete_stack(StackName=stack_id)
            print(f"Stack '{stack_id}' was scheduled for deletion. It may take a few minutes before the stack is completely deleted.\n")
            # TODO: wait for stack deletion
            self.clear_stack_upload_state()

        except Exception as ex:
            logging.warning("Can't delete stack", exc_info=True)
            print(f"Can't delete CloudFormation stack '{self.uploaded_stack_id}', error = {ex}")
            print("You can use the AWS Console to delete the CloudFormation stack manually. You can still use this wizard to upload another CloudFormation stack with a different name.\n")

    def make_boto_client(self, service_name: str):
        if self.aws_access_key and self.aws_secret_key:
           return boto3.client(service_name,
                               aws_access_key_id=self.aws_access_key,
                               aws_secret_access_key=self.aws_secret_key,
                               region_name=self.aws_region)

        # TODO: use default credentials
        return None

    def clear_aws_state(self):
        self.available_cluster_arns = None
        self.cluster_arn = None
        self.external_id = None
        self.workflow_starter_access_key = None
        self.uploaded_stack_id = None
        self.save()

    def clear_stack_upload_state(self):
        self.uploaded_stack_id = None
        self.external_id = None
        self.workflow_starter_access_key = None
        self.assumable_role_arn = None
        self.task_execution_role_arn = None
        self.workflow_starter_arn = None
        self.stack_upload_started_at = None
        self.stack_upload_succeeded = None
        self.stack_upload_finished_at = None
        self.save()

    def generate_random_key(self):
        return ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for _ in range(KEY_LENGTH))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('--environment',
                        help='CloudReactor deployment environment')
    parser.add_argument('--log-level',
                        help=f"Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Defaults to {DEFAULT_LOG_LEVEL}.")

    args = parser.parse_args()

    deployment_environment = args.environment

    log_level = (args.log_level or os.environ.get('WIZARD_LOG_LEVEL', DEFAULT_LOG_LEVEL)).upper()
    numeric_log_level = getattr(logging, log_level, None)
    if not isinstance(numeric_log_level, int):
        logging.warning(f"Invalid log level: {log_level}, defaulting to {DEFAULT_LOG_LEVEL}")
        numeric_log_level = getattr(logging, DEFAULT_LOG_LEVEL, None)

    logging.basicConfig(level=numeric_log_level,
                        format=f"%(levelname)s: %(message)s")
    print_banner()

    logging.debug(f"CloudReactor Base URL = '{CLOUDREACTOR_API_BASE_URL}'")

    bucket_suffix = ''
    file_suffix = ''
    if deployment_environment and (deployment_environment != 'production'):
        bucket_suffix = "-" + deployment_environment
        file_suffix = "." + deployment_environment

    bucket_name = 'cloudreactor-customer-setup' + bucket_suffix

    wizard = None

    if os.path.isfile(SAVED_STATE_FILENAME):
        try:
            with open(SAVED_STATE_FILENAME) as f:
                wizard = jsonpickle.decode(f.read())
        except Exception as ex:
            print("Couldn't read saved state, starting over. Sorry about that!")
    else:
        print("No save state found, starting a new saved_settings.json.")

    if wizard is None:
        wizard = Wizard(deployment=deployment_environment)

    wizard.run()
