from typing import List, Optional

import argparse
from datetime import datetime
import json
import os
import logging
import random
import re
import string
import time
import urllib.parse

import jsonpickle
import urllib3
import boto3
import questionary
from jinja2 import Environment, FileSystemLoader
import yaml

DEFAULT_LOG_LEVEL = 'ERROR'
SAVED_STATE_FILENAME = 'saved_settings.json'
DEFAULT_SUFFIX = ' (Default)'
UNSET_STRING = '(Not Set)'
EMPTY_LIST_STRING = '(Empty list, to be entered manually later)'
HELP_MESSAGE = 'Please contact support@cloudreactor.io for help.'

AWS_REGIONS = [
    'us-east-1',
    'us-east-2',
    'us-west-1',
    'us-west-2',
    'us-gov-east-1',
    'us-gov-west-1',
    'ap-west-1',
    'ap-south-1',
    'ap-northeast-1',
    'ap-northeast-2',
    'ap-northeast-3',
    'eu-central-1',
    'eu-west-1',
    'eu-west-2',
    'eu-west-3',
    'eu-north-1',
    'me-south-1',
    'sa-east-1',
    'ca-central-1',
    'cn-north-1',
    'cn-northwest-1',
]

DEFAULT_AWS_REGION = 'us-west-2'

DEFAULT_RUN_ENVIRONMENT_NAME = 'staging'
CREATE_NEW_ECS_CLUSTER_CHOICE = 'Create new ECS cluster ...'
ECS_CLUSTER_NAME_REGEX = re.compile(r'[a-zA-Z][-a-zA-Z0-9]{0,254}')
DEFAULT_ECS_CLUSTER_NAME = 'staging'

KEY_LENGTH = 32

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

def print_banner():
    with open('banner.txt') as f:
        print(f.read())


class Wizard(object):
    MODE_INTERVIEW = 'interview'
    MODE_EDIT = 'edit'

    NUMBER_TO_PROPERTY = {
        '1': ['aws_region', 'AWS region'],
        '2': ['aws_access_key', 'AWS access key'],
        '3': ['aws_secret_key', 'AWS secret key'],        
        '4': ['cluster_arn', 'AWS ECS Cluster'],
        '5': ['subnets', 'Subnet(s)'],
        '6': ['security_groups', 'Security group(s)'],
        '7': ['stack_name', 'CloudReactor permissions CloudFormation stack name'],
        '8': ['api_key', 'CloudReactor API key'],    
    }

    def __init__(self, deployment: str):
        self.deployment_environment = deployment
        self.aws_region = None
        self.aws_access_key = None
        self.aws_secret_key = None
        self.aws_account_id = None
        self.available_cluster_arns = None
        self.cluster_arn = None        
        self.vpc_id = None
        self.was_vpc_created_by_wizard = None
        self.subnets = None
        self.security_groups = None
        self.api_key = None
        self.stack_name = None
        self.stack_id_to_update = None
        self.external_id = None
        self.workflow_starter_access_key = None
        self.uploaded_stack_id = None
        self.assumable_role_arn = None
        self.task_execution_role_arn = None
        self.workflow_starter_arn = None
        self.stack_upload_started_at = None
        self.stack_upload_succeeded = None
        self.stack_upload_finished_at = None
        self.stack_upload_status = None
        self.stack_upload_status_reason = None
        self.saved_run_environment_uuid = None
        self.saved_run_environment_name = None

        self.mode = Wizard.MODE_INTERVIEW

    def reset(self):
        self.aws_region = None
        self.aws_access_key = None
        self.aws_secret_key = None
        self.api_key = None
        self.saved_run_environment_name = None
        self.stack_name = None
        self.stack_id_to_update = None
        self.saved_run_environment_uuid = None
        self.mode = Wizard.MODE_INTERVIEW
        self.clear_aws_state()

    def clear_aws_state(self):
        self.aws_account_id = None
        self.available_cluster_arns = None
        self.cluster_arn = None        
        self.vpc_id = None
        self.was_vpc_created_by_wizard = None
        self.subnets = None
        self.security_groups = None
        self.clear_stack_upload_state()

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
        self.stack_upload_status = None
        self.stack_upload_status_reason = None
        self.save()

    def set_deployment_environment(self, deployment: str):
        self.deployment_environment = deployment

    def print_menu(self):
        for choice in self.make_property_choices():
            print(choice)
        print()

    def make_property_choices(self):
        choices = []
        property_count = len(Wizard.NUMBER_TO_PROPERTY)
        for i in range(property_count):
            n = i + 1
            arr = Wizard.NUMBER_TO_PROPERTY[str(n)]
            attr = arr[0]
            v = self.__dict__[attr]

            if v and (attr == 'aws_secret_key'):
                v = v[0] + ('*' * max(len(v) - 2, 0)) + v[-1]
            elif attr in ['subnets', 'security_groups']:
                v = self.list_to_string(v)

            choices.append(f"{n}. {arr[1]}: {str(v or UNSET_STRING)}")
        return choices

    def run(self):
        finished = False
        first_run = True
        while not finished:
            rv = None
            if self.saved_run_environment_uuid:
                rv = self.handle_run_environment_saved()
            elif self.uploaded_stack_id and not self.stack_upload_finished_at:
                rv = self.wait_for_role_stack_upload()    

            if rv is None:
                self.print_menu()

                if (not first_run) and (self.mode == Wizard.MODE_INTERVIEW):
                    rv = questionary.confirm("Continue step-by-step interview? (n switches to editing settings)").ask()
                    if not rv:
                        self.mode = Wizard.MODE_EDIT
                        self.save()

                first_run = False
                proceed = True

                while proceed:
                    if wizard.mode == Wizard.MODE_INTERVIEW:
                        proceed = self.interview()

                        if proceed is None:
                            wizard.mode = Wizard.MODE_EDIT
                            self.save()
                    else:
                        proceed = self.edit()

                        if proceed and self.are_all_properties_set():
                            if self.handle_all_settings_entered():
                                proceed = False

    def interview(self):
        property_count = len(Wizard.NUMBER_TO_PROPERTY)
        for i in range(property_count):
            n = i + 1
            arr = Wizard.NUMBER_TO_PROPERTY[str(n)]

            if self.__dict__[arr[0]] is None:
                rv = self.edit_property(n)
                if rv is None:
                    return None

        self.handle_all_settings_entered()

        return None

    def handle_all_settings_entered(self):
        rv = questionary.confirm("All settings have been entered. Proceed with CloudReactor setup?").ask()

        # TODO: check saved state in case we uploaded already
        if rv:
            return self.create_or_update_run_environment()

        return None

    def edit(self):
        choices = self.make_property_choices()

        n = len(choices)

        choices.append(f"{n + 1}. Back to interview")
        choices.append(f"{n + 2}. Quit")

        selected = questionary.select(
            "Which setting do you want to edit?",
            choices=choices).ask()

        if selected is None:
            print("\nExiting for now. You can finish the setup process later by running this wizard again.\n")
            exit(0)

        dot_index = selected.find('.')
        number = int(selected[:dot_index])

        if number == n + 1:
            self.mode = Wizard.MODE_INTERVIEW
            return True
        elif number == n + 2:
            exit(0)

        return self.edit_property(number)

    def are_all_properties_set(self):
        property_count = len(Wizard.NUMBER_TO_PROPERTY)
        for i in range(property_count):
            n = i + 1
            arr = Wizard.NUMBER_TO_PROPERTY[str(n)]

            if self.__dict__[arr[0]] is None:
                return False
        return True                

    def edit_property(self, n):
        arr = Wizard.NUMBER_TO_PROPERTY[str(n)]
        p = arr[0]

        if p == 'aws_region':
            return self.ask_for_aws_region()
        elif p == 'aws_access_key':
            return self.ask_for_aws_access_key()
        elif p == 'aws_secret_key':
            return self.ask_for_aws_secret_key()
        elif p == 'stack_name':
            return self.ask_for_role_stack_name_and_upload()
        elif p == 'subnets':
            return self.ask_for_subnets()
        elif p == 'security_groups':
            return self.ask_for_security_groups()
        elif p == 'api_key':
            return self.ask_for_api_key()
        elif p == 'cluster_arn':
            return self.ask_for_ecs_cluster_arn()
        else:
            print(f"{n} is not a valid choice. Please try another choice. [{p}]")
            return None

    def ask_for_aws_region(self):
        old_aws_region = self.aws_region
        default_aws_region = old_aws_region or os.environ.get('AWS_REGION') or \
                             os.environ.get('AWS_DEFAULT_REGION')

        choices = AWS_REGIONS

        if default_aws_region:
            choices = [default_aws_region + DEFAULT_SUFFIX] + choices 

        self.aws_region = questionary.select(f"Which AWS region will you run ECS tasks?",
            choices=choices).ask()

        if self.aws_region is None:
            print("Skipping AWS region for now.\n")
            return None

        self.aws_region = self.aws_region.replace(DEFAULT_SUFFIX, '')

        print(f"Using AWS region {wizard.aws_region}.\n")

        if old_aws_region != self.aws_region:
            self.clear_aws_state()

        self.save()
        return self.aws_region

    def ask_for_aws_access_key(self):
        print("""
To allow this wizard to create AWS resources for you, it needs an AWS access key.
The access key needs to be associated with a user that has the following permissions:
- Upload CloudFormation stack
- Create IAM Roles
- List ECS clusters, VPCs, subnets, and security groups
- Create ECS clusters (if using the wizard to create an ECS cluster)
- Create VPCs, subnets, internet gateways, and security groups (if using the wizard to create a VPC)

The access key and secret key are not sent to CloudReactor.
""")

        old_aws_access_key = self.aws_access_key
       
        # TODO
        #q = 'What AWS access key do you want to use? Type "none" to use the default permissions on this machine.'
        q = 'What is the AWS access key do you want to use for this wizard?'

        if old_aws_access_key:
            q += f" [{old_aws_access_key}]"

        self.aws_access_key = questionary.text(q).ask() or old_aws_access_key

        if old_aws_access_key != self.aws_access_key:
            self.clear_aws_state()

        self.validate_aws_access()
        return self.aws_access_key

    def ask_for_aws_secret_key(self):
        old_aws_secret_key = self.aws_secret_key
        #TODO
        #q = 'What AWS secret key do you want to use? Type "none" to use the default permissions on this machine.'
        q = 'What is the AWS secret key corresponding to your AWS access key?'

        if old_aws_secret_key:
            q += f" [{old_aws_secret_key}]"

        self.aws_secret_key = questionary.password(q).ask() or old_aws_secret_key

        if self.aws_secret_key != self.aws_access_key:
            self.clear_aws_state()

        self.validate_aws_access()
        return self.aws_secret_key

    def ask_for_role_stack_name_and_upload(self):
        print("To allow CloudReactor to run tasks on your behalf, you'll need to install an AWS CloudFormation stack that grants CloudReactor permissions to control tasks.")
        print(f"To see the resources that will be added, please see {self.make_cloudformation_role_template_url()}")

        cf_client = self.make_boto_client('cloudformation')

        if not cf_client:
            print("You must set your AWS credentials before installing a CloudFormation stack.\n")
            return None

        default_stack_name=self.make_default_role_stack_name()
        if self.stack_name and (not self.uploaded_stack_id):
            default_stack_name = self.stack_name

        old_uploaded_stack_name = None
        if self.uploaded_stack_id:
            old_uploaded_stack_name = self.stack_name

        rv = self.ask_for_stack_name(
            default_stack_name=default_stack_name,
            old_uploaded_stack_name=old_uploaded_stack_name,
            create_or_update_message="If you've never set up CloudReactor before, you should install a new CloudFormation stack.",
            purpose=' to grant CloudReactor permissions to control tasks',
            cf_client=cf_client
        )

        if rv is None:
            print("Skipping stack name for now.\n")
            return None

        self.stack_name, self.stack_id_to_update, reuse_stack = rv
        self.uploaded_stack_id = None

        self.save()
                
        if (not reuse_stack) and (self.uploaded_stack_id is None):
            rv = self.start_role_cloudformation_template_upload(cf_client=cf_client)
            if not rv:
                return None

        if self.uploaded_stack_id and not self.stack_upload_finished_at:
            rv = self.wait_for_role_stack_upload(cf_client=cf_client)

            if rv:
                print(f"The CloudFormation stack installation was successful.")
                return rv

            return None
        else:
            return self.uploaded_stack_id            


    def ask_for_stack_name(self, default_stack_name, old_uploaded_stack_name, 
        create_or_update_message, purpose, cf_client=None):
        if not cf_client:
            cf_client = self.make_boto_client('cloudformation')

        if not cf_client:
            print("You must set your AWS credentials before installing a CloudFormation stack.\n")
            return None

        existing_stacks = self.list_stacks(cf_client=cf_client)
        existing_stack_names = [stack['name'] for stack in (existing_stacks or [])]

        should_create = True
        if len(existing_stack_names) > 0:
            print()

            if create_or_update_message:
                print(create_or_update_message)

            selection = questionary.select(
                f'Do you want to install a new CloudFormation stack{purpose} or update and use an existing one?',
                choices=['Install a new stack', 'Update and use an existing stack']).ask()

            if selection is None:
                return None

            should_create = (selection.find('new') >= 0)

        if should_create:
            good_stack_name = None
            reuse_stack = False
            while not good_stack_name:
                stack_name = questionary.text(
                    f"What do you want to name the CloudFormation stack{purpose}? [{default_stack_name}]").ask()

                if stack_name is None:
                    return None

                if not stack_name:
                    stack_name = default_stack_name

                if old_uploaded_stack_name and (stack_name == old_uploaded_stack_name):
                    print(f"Reusing previously installed stack '{stack_name}'.")
                    good_stack_name = stack_name
                    reuse_stack = True
                elif stack_name in existing_stack_names:
                    print(f"The name '{stack_name}' conflicts with an existing stack name. Please choose another name.")
                elif CLOUDFORMATION_STACK_NAME_REGEX.fullmatch(stack_name) is None:
                    print(f"'{stack_name}' is not a valid CloudFormation stack name. Stack names can only contain alphanumeric characters and dashes, no underscores.")
                else:
                    print(f"New stack will be named '{stack_name}'.\n")
                    good_stack_name = stack_name

            return stack_name, None, reuse_stack
        else:
            stack_name = questionary.select("Which CloudFormation stack do you want to update and use?",
                                            choices=existing_stack_names).ask()

            if stack_name is None:
                return None

            selected_stack = None
            for stack in existing_stacks:
                if stack.get('name') == stack_name:
                    selected_stack = stack

            if selected_stack is None:
                logging.error(f"Can't find existing stack '{stack_name}'!")
                return None

            existing_stack_status = selected_stack.get('status') or ''

            if existing_stack_status.find('PROGRESS') >= 0:
                print(f"Stack {stack_name} is still in progress with status '{existing_stack_status}', please try again later.\n")
                self.uploaded_stack_id = None
                return None

            return stack_name, selected_stack['stack_id'], False
       
    def make_default_role_stack_name(self):
        name = 'CloudReactor'

        if self.deployment_environment and (self.deployment_environment != 'production'):
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
        except Exception:
            logging.warning("Can't list clusters", exc_info=True)

        if (self.available_cluster_arns is None) or (len(self.available_cluster_arns) == 0):
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

    def create_cluster(self, ecs_client=None):
        if ecs_client is None:
            ecs_client = self.make_boto_client('ecs')

        if ecs_client is None:
            print("You must set your AWS credentials before creating an ECS cluster.\n")
            return None

        good_cluster_name = False
        while not good_cluster_name:
            cluster_name = questionary.text(
                f"What do you want to name the ECS cluster?").ask()

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
            self.available_cluster_arns = [self.cluster_arn] + (self.available_cluster_arns or [])

            print(f"Successfully created ECS cluster {self.cluster_arn} in region {self.aws_region}.\n")
            self.save()
            return self.cluster_arn
        except Exception as ex:
            logging.warning("Failed to create ECS cluster.")
            print(f"Failed to create ECS cluster: {ex}")
            return None

    def start_role_cloudformation_template_upload(self, cf_client=None):
        if not cf_client:
            cf_client = self.make_boto_client('cloudformation')

        if not cf_client:
            print("You must set your AWS credentials before installing a CloudFormation stack.\n")
            return None

        self.stack_upload_started_at = datetime.now()

        try:
            resp = None
            if self.stack_id_to_update:
                resp = cf_client.update_stack(
                    StackName=self.stack_id_to_update,
                    TemplateURL=self.make_cloudformation_role_template_url(),
                    Parameters=[
                        {
                            'ParameterKey': 'ExternalID',
                            'UsePreviousValue': True,
                        },
                        {
                            'ParameterKey': 'WorkflowStarterAccessKey',
                            'UsePreviousValue': True,
                        }
                    ],
                    Capabilities=[
                        'CAPABILITY_NAMED_IAM'
                    ]
                )
            else:
                self.external_id = self.generate_random_key()
                self.workflow_starter_access_key = self.generate_random_key()
                resp = cf_client.create_stack(
                    StackName=self.stack_name,
                    TemplateURL=self.make_cloudformation_role_template_url(),
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
            ex_str = str(ex)
            if self.stack_id_to_update and (ex_str.find('No updates are to be performed') >= 0):
                print(f"No stack updates were necessary. Using existing stack name '{self.stack_name}'.\n")
                self.uploaded_stack_id = self.stack_id_to_update
                return self.uploaded_stack_id
            else:
                logging.warning("Failed to install stack", exc_info=True)
                print(f"Failed to install stack: {ex}")                

                if ex_str.find('AlreadyExistsException'):
                    rv = questionary.confirm(f"That stack already exists. Delete it?").ask()

                    if rv:
                        self.delete_role_stack(cf_client)

                self.clear_stack_upload_state()
                return None

        self.save()

        print(f"Started CloudFormation role template installation for stack '{self.stack_name}', stack ID is {self.uploaded_stack_id}.")
        return self.uploaded_stack_id

    def wait_for_role_stack_upload(self, cf_client=None):
        if not self.uploaded_stack_id:
            logging.error("wait_for_role_stack_upload() called but, but no stack ID was saved.")
            return False

        if not cf_client:
            cf_client = self.make_boto_client('cloudformation')

        if not cf_client:
            print("Your AWS credentials are invalid. Please check them and try again.\n")
            return None

        stack = self.wait_for_stack_upload(self.uploaded_stack_id, 
            self.stack_name, cf_client)

        if stack is None:
            return None

        self.stack_upload_finished_at = datetime.now()        
        self.stack_upload_status = stack['StackStatus']

        if self.stack_upload_status in CLOUDFORMATION_SUCCESSFUL_STATUSES:
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

            params = stack['Parameters'] or []

            for param in params:
                param_key = param['ParameterKey']
                param_value = param['ParameterValue']

                if param_key == 'ExternalID':
                    self.external_id = param_value
                elif param_key == 'WorkflowStarterAccessKey':
                    self.workflow_starter_access_key = param_value

            if self.external_id and self.workflow_starter_access_key and \
                    self.assumable_role_arn and self.task_execution_role_arn and \
                    self.workflow_starter_arn:
                self.stack_upload_succeeded = True
                self.save()
                return True

            print('Something was missing from the stack output. ' + HELP_MESSAGE + '\n')
            self.stack_upload_succeeded = False
            self.save()
            return None
        else:
            self.stack_upload_status_reason = stack.get('StackStatusReason')            
            self.stack_upload_succeeded = False
            self.save()

            print(f"The CloudReactor permissions stack upload failed with status '{self.stack_upload_status}' and status reason '{self.stack_upload_status_reason}'.")
            return None

    def wait_for_vpc_stack_upload(self, vpc_stack_id: str,  vpc_stack_name: str,
        cf_client):
        if not vpc_stack_id:
            logging.error("wait_for_vpc_stack_upload() called but, but no vpc_stack_id was specified.")
            return False

        stack = self.wait_for_stack_upload(vpc_stack_id, 
            vpc_stack_name, cf_client)

        if stack is None:
            return None

        stack_upload_status = stack['StackStatus']

        if stack_upload_status in CLOUDFORMATION_SUCCESSFUL_STATUSES:
            outputs = stack['Outputs'] or []
            self.subnets = []
            # TODO add security groups            

            for output in outputs:
                output_key = output['OutputKey']
                output_value = output['OutputValue']
                if output_key == 'VPC':                    
                    self.vpc_id = output_value
                    logging.debug(f"Got VPC {self.vpc_id} from stack output")
                elif output_key == 'SubnetsPrivate':
                    self.subnets = output_value.split(',')
                    logging.debug(f"Got subnets {self.subnets} from stack output")
                elif output_key == 'DefaultTaskSecurityGroup':
                    logging.debug(f"Got security group {output_value} from stack output")
                    self.security_groups = [output_value]
                else:
                    logging.debug(f"Got output '{output_key}' with value '{output_value}'.")                    

            if self.vpc_id and self.subnets and self.security_groups:       
                self.was_vpc_created_by_wizard = True
                self.save()         
                return self.vpc_id

            print('Something was missing from the stack output. ' + HELP_MESSAGE + '\n')
            return None
        else:
            stack_upload_status_reason = stack['StackStatusReason']
            print(f"The VPC stack upload failed with status '{stack_upload_status}' and status reason '{stack_upload_status_reason}'.")
            return None


    def wait_for_stack_upload(self, stack_id, stack_name, cf_client):
        while True:
            resp = None
            try:
                resp = cf_client.describe_stacks(
                    StackName=stack_id
                )
            except Exception:
                logging.warning("Can't describe CloudFormation stacks, re-creating client ...", 
                    exc_info=True)
                time.sleep(10)
                cf_client = self.make_boto_client('cloudformation')

            if resp:
                stacks = resp['Stacks']

                if len(stacks) == 0:
                    print(f"CloudFormation stack '{stack_name}' was deleted, please check your settings and try again.\n")
                    return None

                stack = stacks[0]
                status = stack['StackStatus']

                if status in CLOUDFORMATION_IN_PROGRESS_STATUSES:
                    print(f"CloudFormation stack installation is still in progress ({status}). Waiting 10 seconds before checking again ...")
                    time.sleep(10)                
                else:
                    return stack


    def delete_stack(self, stack_id_or_name, cf_client=None):
        if not stack_id_or_name:
            logging.error("stack_id_or_name is empty")
            return None

        if cf_client is None:
            cf_client = self.make_boto_client('cloudformation')

        if cf_client is None:
            print("AWS authentication is not working, can't delete CloudFormation stack. Please check your credentials.\n")
            return None

        try:
            cf_client.delete_stack(StackName=stack_id_or_name)
            print(f"Stack '{stack_id_or_name}' was scheduled for deletion. It may take a few minutes before the stack is completely deleted.\n")
            return True
        except Exception as ex:
            logging.warning("Can't delete stack", exc_info=True)
            print(f"Can't delete CloudFormation stack '{stack_id_or_name}', error = {ex}")
            print("You can use the AWS Console to delete the CloudFormation stack manually. You can still use this wizard to install another CloudFormation stack with a different name.\n")
            return None

    def delete_role_stack(self, cf_client=None):
        stack_id = self.uploaded_stack_id or self.stack_name
        if not stack_id:
            print("No CloudFormation stack found to delete.")
            return None

        if self.delete_stack(stack_id, cf_client):
            self.clear_stack_upload_state()
            return True

        return None    

    def handle_role_stack_upload_finished(self, cf_client=None):
        if self.stack_upload_succeeded:
            print(f"The installation of the CloudFormation stack for CloudReactor permissions was successful.")

            if self.api_key:
                return self.create_or_update_run_environment()
            else:
                return True
        else:
            reason = self.stack_upload_status_reason or '(Unknown)'
            print(f"The installation of the CloudFormation stack for CloudReactor permissions failed with status '{self.stack_upload_status}' and reason '{reason}'.")
            rv = questionary.confirm('Do you want to delete the stack and try again?').ask()
            if rv:
                self.delete_role_stack(cf_client)

            self.clear_stack_upload_state()
            return False

    def ask_for_subnets(self):
        print()
        print("ECS Tasks require subnets to run in. For more information see https://cloudonaut.io/fargate-networking-101/")
        print("This step allows you to specify the default subnets for tasks associated with a CloudReactor Run Environment, so that CloudReactor can use those subnets when starting or scheduling tasks.")        
        print("If you have existing subnets that contain AWS resources your tasks need to access, you should select them below.")        
        print("If you don't have existing subnets, this wizard can create them for you now.")
        print("You can also choose to skip this step and enter the subnets after the Run Environment has been created.")
        print()

        choices = []

        subnets_str = self.list_to_string(self.subnets)

        if self.subnets is not None:
            choices = ['Use previously entered subnets: ' + subnets_str]

        choices += [
            'Create a new VPC which includes subnets',
            'Select existing subnet(s)',
            #'Enter subnets manually',
            'Skip subnets'
        ]

        rv = questionary.select('How would you like to specify subnets?',
                                choices=choices).ask()

        if rv is None:
            return None

        if rv.startswith('Use previous'):
            print(f"Using previously entered subnets {subnets_str}.\n")
            return self.subnets

        if rv.startswith('Skip'):
            print('Skipping subnets for now. You can add them manually later.\n')
            self.subnets = []
            self.save()
            return self.subnets

        is_create = rv.startswith('Create')
        is_select = rv.startswith('Select')

        rv = None
        if is_create:
            rv = self.create_vpc()
        elif is_select:
            ec2_client = self.make_boto_client('ec2')            
            if not ec2_client:
                print("You need to specify your AWS credentials before selecting subnets.\n")
                return None

            rv = self.ask_for_vpc(ec2_client)
            
        if not rv:
            return None

        if is_create or self.was_vpc_created_by_wizard:
            return self.subnets

        if is_select:
            return self.ask_for_subnets_in_vpc(ec2_client)

        return None

    def ask_for_security_groups(self):
        print()
        print("ECS Tasks require at least one security group that allows outbound access to the public internet.")
        print("This step allows you to specify the default security groups to give tasks associated with a CloudReactor Run Environment, so that CloudReactor can assign those security groups when starting or scheduling tasks.")
        print("If you have existing security groups you want to assign to your tasks by default, you should select them below.")
        print("If you don't an existing security group, this wizard can create it for you now.")        
        print("You can also choose to skip this step and enter the security groups after the Run Environment has been created.")
        print()

        choices = []

        security_groups_str = self.list_to_string(self.security_groups)

        if self.security_groups is not None:
            choices = ['Use previously entered security groups: ' + security_groups_str]

        choices += [
            'Create a new VPC which includes a default security group',
            'Select existing security group(s)',
            #'Enter security groups manually',
            'Skip security groups'
        ]

        rv = questionary.select('How would you like to specify security groups?',
                                choices=choices).ask()

        if rv is None:
            return None

        if rv.startswith('Use previous'):
            print(f"Using previously entered security groups {security_groups_str}.\n")
            return self.security_groups

        if rv.startswith('Skip'):
            print('Skipping security groups for now. You can add them manually later.\n')
            self.security_groups = []
            self.save()
            return self.security_groups

        is_create = rv.startswith('Create')
        is_select = rv.startswith('Select')

        rv = None
        ec2_client = None
        if is_create:
            rv = self.create_vpc()
        elif is_select:
            ec2_client = self.make_boto_client('ec2')            
            if not ec2_client:
                print("You need to specify your AWS credentials before selecting security groups.\n")
                return None
            rv = self.ask_for_vpc(ec2_client)
            
        if not rv:
            return None

        if is_create or self.was_vpc_created_by_wizard:            
            return self.security_groups

        if is_select:
            return self.ask_for_security_groups_in_vpc(ec2_client)

        return None


    def ask_for_vpc(self, ec2_client):
        vpc_ids = self.list_vpcs(ec2_client)
        create_choice = 'Create a new VPC ...'

        if vpc_ids:
            choices = []

            current_vpc_choice = None
            if self.vpc_id and (self.vpc_id in vpc_ids):
                current_vpc_choice = self.vpc_id + ' (current)'                
                choices.append(current_vpc_choice)
                vpc_ids.remove(self.vpc_id)
                choices += vpc_ids
            else:
                choices += vpc_ids

            choices.append(create_choice)

            vpc_id = questionary.select("Which VPC do you want to use?", choices=choices).ask()

            if vpc_id is None:
                return None
                
            if vpc_id != create_choice:
                if vpc_id != current_vpc_choice:                
                    self.vpc_id = vpc_id
                    self.save()
                return vpc_id
        else:
            rv = questionary.confirm('Create a new VPC?').ask()

            if not rv:
                return None

        return self.create_vpc()

    def create_vpc(self):
        print("""
This wizard can create a VPC suitable for running ECS tasks, along with subnets and a security group.
For more information, see https://docs.aws.amazon.com/vpc/latest/userguide/VPC_Subnets.html

To create the VPC, this wizard uses a modified version of a CloudFormation template created
by cloudonaut (https://cloudonaut.io/templates-for-aws-cloudformation/). 
Big thanks to cloudonaut for creating this!
""")

        cf_client = self.make_boto_client('cloudformation')

        if cf_client is None:
            print("You must set your AWS credentials before creating a VPC.\n")
            return None

        done = False   
        num_zones = 2     
        while not done:        
            rv = questionary.text('How many availability zones do you want to use? [2]').ask()

            if rv is None:
                return None

            num_zones = 2
            if rv:
                try:
                    num_zones = int(rv)
                except ValueError:
                    print("The number of availability zones must be between 1 and 3.")
                    continue

                if num_zones < 1 or num_zones > 3:
                    print("The number of availability zones must be between 1 and 3.")
                    continue
            else:
                num_zones = 2

            done = True

        second_octet = 0
        done = False
        while not done:        
            rv = questionary.text('The subnets will be in the range 10.[n].0.0/16. What should n be? [0]').ask()

            if rv is None:
                return None

            second_octet = 0
            if rv:
                try:
                    second_octet = int(rv)
                except ValueError:
                    print("n should be between 0 and 255.")
                    continue

                if second_octet < 0 or second_octet > 255:
                    print("n should be between 0 and 255.")
                    continue
            else:
                second_octet = 0

            done = True

        vpc_template = self.make_vpc_template(num_availability_zones=num_zones,
            second_octet=second_octet)

        logging.debug(f"vpc_template = {vpc_template}")

        rv = self.ask_for_stack_name(
            default_stack_name='ECS-VPC',
            old_uploaded_stack_name=None,
            create_or_update_message=None,
            purpose=' to create a VPC',
            cf_client=cf_client
        )

        if rv is None:
            print("Skipping VPC creation for now.\n")
            return None

        vpc_stack_name, vpc_stack_id_to_update, reuse_stack = rv

        vpc_stack_id = vpc_stack_id_to_update
        if not reuse_stack:
            rv = self.start_vpc_cloudformation_template_upload(vpc_stack_name,
                vpc_stack_id_to_update, vpc_template, cf_client)

            if rv is None:
                print("Can't create or update VPC CloudFormation stack.\n")
                return None

            vpc_stack_id = rv

        if vpc_stack_id:
            vpc_id = self.wait_for_vpc_stack_upload(vpc_stack_id, 
                vpc_stack_name, cf_client)
                            
            if vpc_id is None:
                print(f"Something was wrong with the VPC CloudFormation stack. {HELP_MESSAGE}\n")
                return None
        
        print(f"Successfully created VPC {self.vpc_id} in region {self.aws_region}.")

        return vpc_id

    def make_vpc_template(self, num_availability_zones, second_octet) -> str:
        env = Environment(
            loader=FileSystemLoader('./templates/')
        )

        template = env.get_template('vpc.yml.j2')

        data = {
            'az_count': num_availability_zones,
            'second_octet': second_octet,
        }

        return template.render(data)

    def start_vpc_cloudformation_template_upload(self, vpc_stack_name: str, 
        vpc_stack_id_to_update: str, vpc_template: str,
        cf_client=None):
        if not cf_client:
            cf_client = self.make_boto_client('cloudformation')

        if not cf_client:
            print("Your AWS credentials are invalid. Please check them and try again.\n")
            return None

        try:
            resp = None

            if vpc_stack_id_to_update:
                resp = cf_client.update_stack(
                    StackName=vpc_stack_id_to_update,
                    TemplateBody=vpc_template
                )
            else:    
                resp = cf_client.create_stack(
                    StackName=vpc_stack_name,
                    TemplateBody=vpc_template
                )

            logging.debug('Got stack response:')
            logging.debug(resp)

            vpc_stack_id = resp['StackId']
            print(f"Started CloudFormation VPC template installation for VPC stack '{vpc_stack_name}', stack ID is {vpc_stack_id}.")
            return vpc_stack_id
        except Exception as ex:
            ex_str = str(ex)

            if vpc_stack_id_to_update and (ex_str.find('No updates are to be performed') >= 0):
                print(f"No stack updates were necessary. Using existing stack name '{vpc_stack_name}'.\n")
                return vpc_stack_id_to_update

            logging.warning("Failed to install stack", exc_info=True)
            print(f"Failed to install stack: {ex}")

            if ex_str.find('AlreadyExistsException'):
                rv = questionary.confirm(f"That stack already exists. Delete it?").ask()
                if rv:
                    self.delete_stack(vpc_stack_name, cf_client)

            return None

    def ask_for_subnets_in_vpc(self, ec2_client) -> Optional[List[str]]:
        available_subnets = self.list_subnets(ec2_client)

        if available_subnets is None:
            return None

        if len(available_subnets) == 0:
            # TODO
            return None
        else:
            print("""
You can select one or more subnets to use to run ECS tasks. 
Normally these subnets should be private, unless you need to allow inbound access from the public internet like a web server.
""")

            selected_subnets = []
            done_choice = 'Done selecting subnets'

            choices = [done_choice]

            for subnet in available_subnets:
                arn = subnet['SubnetArn']
                subnet_id = arn[(arn.rfind('/') + 1):]
                subnet_name = None
                tags = subnet.get('Tags') or []
                for tag in tags:
                    if tag['Key'] == 'Name':
                        subnet_name = tag['Value']
                choice_parts = [subnet_id]
                
                if subnet_name:
                  choice_parts.append(subnet_name)

                choice_parts += [subnet['CidrBlock'], subnet['AvailabilityZone']]
                choices.append(' | '.join(choice_parts))

            while True:
                rv = questionary.select('Choose a subnet to add:', choices=choices).ask()
                if rv is None:
                    print("Skipping subnets for now.")
                    return None

                if rv == done_choice:
                    self.subnets = []

                    for subnet_choice in selected_subnets:
                        space_index = subnet_choice.find(' ')
                        self.subnets.append(subnet_choice[0:space_index])

                    print(f"Using subnets {self.list_to_string(self.subnets)}")
                    self.save()
                    return self.subnets

                selected_subnets.append(rv)
                choices.remove(rv)
                print(f"Selected subnets so far: {self.list_to_string(selected_subnets)}")

    def ask_for_security_groups_in_vpc(self, ec2_client) -> Optional[List[str]]:
        available_security_groups = self.list_security_groups(ec2_client)

        if available_security_groups is None:
            return None            

        if len(available_security_groups) == 0:
            # TODO
            return None
        else:
            print("""
You can select one or more security groups here. However, most likely you only need a single one,
which allows outbound access to the public internet.
""")            
            selected_security_groups = []
            done_choice = 'Done selecting security groups'
            choices = [done_choice] + [f"{sg['GroupId']} ({sg['GroupName']})" for sg in available_security_groups]

            while True:
                rv = questionary.select('Choose a security group to add:', choices=choices).ask()
                if rv is None:
                    print("Skipping security groups for now.")
                    return None

                if rv == done_choice:
                    self.security_groups = selected_security_groups
                    print(f"Using security groups {self.list_to_string(self.security_groups)}")
                    self.save()
                    return self.security_groups

                space_index = rv.find(' ')
                security_group_id = rv[0:space_index]

                selected_security_groups.append(security_group_id)
                choices.remove(rv)
                print(f"Selected security_groups so far: {self.list_to_string(selected_security_groups)}")

    def ask_for_api_key(self):
        # TODO: allow user to get an API key on website
        print('To enable monitoring and management for your Tasks and Workflows, please contact us at help@cloudreactor.io for a free CloudReactor account and obtain an API key.')

        q = "What is your CloudReactor API key?"

        old_api_key = self.api_key
        if old_api_key:
            q += f" [{old_api_key}]"

        self.api_key = questionary.text(q).ask() or old_api_key

        if not self.api_key:
            print("Skipping CloudReactor API key for now.")
            return None

        print()

        existing_run_environments = self.list_run_environments()

        if existing_run_environments is None:
            print(f"The CloudReactor API key '{self.api_key}' is not valid. Please check that it is correct.\n")
            self.api_key = None
        elif len(existing_run_environments) == 0:
            print('No current Run Environments found. Please create a new one.\n')
        else:
            # Actually this is the number in the first page, but that should be sufficient
            print(f"There are currently {len(existing_run_environments)} Run Environments in your organization:")

            for run_environment in existing_run_environments:
                print("- " + run_environment['name'])

            print('Your CloudReactor API key is valid.\n')

        self.save()

        return self.api_key

    def make_default_run_environment_name(self):
        if self.cluster_arn:
            name = self.cluster_arn
            slash_index = name.rfind('/')
            if slash_index >= 0:
                name = name[(slash_index + 1):]
            return re.sub(r'[^A-Za-z-]+', '', name) or DEFAULT_RUN_ENVIRONMENT_NAME
        return DEFAULT_RUN_ENVIRONMENT_NAME

    def create_or_update_run_environment(self):
        print("The CloudReactor permissions CloudFormation stack has been uploaded successfully.")
        print("The final step is to create or update a Run Environment in CloudReactor with the corresponding settings.")

        existing_run_environments = self.list_run_environments()

        create_new_choice = 'Create a new Run Environment'
        run_environment_uuid: str = None
        run_environment_name: str = None
        if existing_run_environments:            
            choices = [run_environment['name'] for run_environment in existing_run_environments]
            choices.append(create_new_choice)            
            run_environment_name = questionary.select("Which Run Environment do you want to update?", choices=choices).ask()
            if run_environment_name is None:
                return None

            if run_environment_name != create_new_choice:
                run_environment_uuid = [run_environment['uuid'] for run_environment \
                    in existing_run_environments if run_environment['name'] == run_environment_name][0]
            
        if not run_environment_uuid:
            q = 'What do you want to name your Run Environment? Common names are "staging" or "production".'            
            run_environment_name = questionary.text(q).ask()
            if not run_environment_name:
                return None

        http_method = 'POST'
        url = CLOUDREACTOR_API_BASE_URL + '/api/v1/run_environments/'

        if run_environment_uuid:
            print(f"Updating Run Environment '{run_environment_name}' ...\n")
            http_method = 'PATCH'
            url += (run_environment_uuid + '/')
        else:    
            print(f"Creating Run Environment '{run_environment_name}'.\n")
               
        ecs_caps = {
            'type': 'AWS ECS',
            'default_launch_type': 'FARGATE',
            'supported_launch_types': ['FARGATE'],
            'default_cluster_arn': self.cluster_arn,
            'default_execution_role': self.task_execution_role_arn,
        }

        if self.subnets:
            ecs_caps['default_subnets'] = self.subnets

        if self.security_groups:
            ecs_caps['default_security_groups'] = self.security_groups

        data = {
            'name': run_environment_name,
            'aws_account_id': self.aws_account_id,
            'aws_default_region': self.aws_region,
            'aws_assumed_role_external_id': self.external_id,
            'aws_workflow_starter_access_key': self.workflow_starter_access_key,
            'aws_events_role_arn': self.assumable_role_arn,
            'aws_workflow_starter_lambda_arn': self.workflow_starter_arn,
            'execution_method_capabilities': [ecs_caps]
        }

        response_ok = False
        response_status = None
        response_body = None
        saved_run_environment = None

        try:
            http = urllib3.PoolManager()
            r = http.request(http_method, url,
                             body=json.dumps(data),
                             headers={
                                 'Authorization': f"Token {self.api_key}",
                                 'Accept': 'application/json',
                                 'Content-Type': 'application/json'
                             }, timeout=10.0)

            response_status = r.status

            response_body = r.data.decode('utf-8')
            saved_run_environment = json.loads(response_body)

            response_ok = (response_status >= 200) and (response_status < 300)
        except urllib3.exceptions.HTTPError as http_error:
            print(f"An error communicating with cloudreactor.io occurred: {http_error}")

        if response_ok:
            self.saved_run_environment_uuid = saved_run_environment.get('uuid')

            if not self.saved_run_environment_uuid:
                print('The Run Environment creation/update response was invalid. ' + HELP_MESSAGE)
                return False

            self.saved_run_environment_name = saved_run_environment['name']
            self.save()
            return True
        else:
            print(f"An error occurred creating the Run Environment.")

            if response_body:
                print(f"Got response status {response_status} and response body: {response_body} from the server")
            else:
                print(f"Got response status {response_status} from the server")

        print()
        return False

    def handle_run_environment_saved(self):
        action = 'updated' if self.saved_run_environment_uuid else 'created'
        print(f"The Run Environment '{self.saved_run_environment_name}' was {action} successfully.\n")
        print("Congratulations, you've completed all the steps to setup your AWS environment!\n")
        print("You can view your new Run Environment at " + self.make_run_environment_url())

        if not self.subnets or not self.security_groups:
            print("You may optionally add default subnets and security groups there.")

        print()    

        choices = [
            '1. Create or update another Run Environment',
            '2. Reset all settings and start over',
            '3. Quit'
        ]

        selected = questionary.select('What would you like to do next?',
                                    choices=choices).ask()

        if selected is None:
            return None

        dot_index = selected.find('.')
        number = int(selected[:dot_index])

        if number == 1:
            self.mode = Wizard.MODE_INTERVIEW
            self.saved_run_environment_name = None
            self.saved_run_environment_uuid = None
            self.cluster_arn = None
            self.vpc_id = None
            self.subnets = None
            self.security_groups = None
            self.was_vpc_created_by_wizard = False
            self.save()
            return True
        elif number == 2:
            self.mode = Wizard.MODE_INTERVIEW
            self.reset()
            return True
        else:
            print("To deploy a task managed and monitored by CloudReactor, please follow the instructions at https://docs.cloudreactor.io/\n")
            print("We hope you enjoy using CloudReactor!")
            print()
            exit(0)

    def make_run_environment_url(self):
        if self.saved_run_environment_uuid is None:
            return None

        host_qualifier = ''
        if self.deployment_environment != 'production':
            host_qualifier = '.' + self.deployment_environment            

        return f"https://dash{host_qualifier}.cloudreactor.io/run_environments/" + \
                urllib.parse.quote(self.saved_run_environment_uuid)

    def make_cloudformation_role_template_url(self):
        host_qualifier = ''
        file_qualifier = ''
        if self.deployment_environment != 'production':
            host_qualifier = '-' + self.deployment_environment
            file_qualifier = '.' + self.deployment_environment

        return f"https://cloudreactor-customer-setup{host_qualifier}.s3-us-west-2.amazonaws.com/cloudreactor-aws-role-template{file_qualifier}.json"

    def make_boto_client(self, service_name: str):
        if self.aws_access_key and self.aws_secret_key:
           return boto3.client(service_name,
                               aws_access_key_id=self.aws_access_key,
                               aws_secret_access_key=self.aws_secret_key,
                               region_name=self.aws_region)

        # TODO: use default credentials
        return None

    def generate_random_key(self) -> str:
        return ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for _ in range(KEY_LENGTH))

    def list_to_string(self, arr) -> str:
        if arr is None:
            return UNSET_STRING

        if len(arr) == 0:
            return EMPTY_LIST_STRING

        return '(' + ', '.join(arr) + ')'

    def list_stacks(self, cf_client=None):
        print(f"Looking for existing CloudFormation stacks in region {self.aws_region} ...")

        if not cf_client:
            cf_client = self.make_boto_client('cloudformation')

        if not cf_client:
            print('We could not determine your existing CloudFormation stacks. Please check your AWS credentials.')
            return None

        resp = None
        try:
            resp = cf_client.list_stacks()
        except Exception as ex:
            logging.warning(f"Failed to list stacks: {ex}")
            print('We could not determine your existing CloudFormation stacks. Please check your AWS credentials and permissions.')
            return None

        existing_stacks = []
        stack_summaries = resp.get('StackSummaries') or []

        for summary in stack_summaries:
            stack_id = summary.get('StackId')
            name = summary.get('StackName')
            status = summary.get('StackStatus')

            if stack_id and name and status and \
                    (status != 'DELETE_COMPLETE') and (status != 'DELETE_FAILED'):
                existing_stacks.append({
                    'stack_id': stack_id,
                    'name': name,
                    'status': status
                })

        print(f"Found {len(existing_stacks)} existing CloudFormation stack(s) in region {self.aws_region}.")

        return existing_stacks

    def list_vpcs(self, ec2_client):
        print(f"Looking for existing VPCs in region {self.aws_region} ...")

        resp = None
        try:
            resp = ec2_client.describe_vpcs(MaxResults=100)
        except Exception as ex:
            logging.warning(f"Failed to list VPCs: {ex}")
            print('We could not determine your existing VPCs. Please check your AWS credentials and permissions.')
            return None

        vpcs = resp['Vpcs']
        print(f"Found {len(vpcs)} VPC(s) in region {self.aws_region}.")
        return [vpc['VpcId'] for vpc in vpcs]

    def list_subnets(self, ec2_client):
        if not self.vpc_id:
            logging.error("list_subnets() called without a VPC")
            return None

        print(f"Looking for existing subnets in VPC {self.vpc_id} ...")

        resp = None
        try:
            resp = ec2_client.describe_subnets(
                Filters=[
                    {
                        'Name': 'vpc-id',
                        'Values': [
                            self.vpc_id,
                        ]
                    },
                ],
                MaxResults=100)
        except Exception as ex:
            logging.warning(f"Failed to list subnets: {ex}")
            print('We could not determine your existing subnets. Please check your AWS credentials and permissions.')
            return None

        logging.debug(f"subnets response = {resp}")

        subnets = resp['Subnets']
        subnet_count = len(subnets)
        print(f"Found {subnet_count} subnet(s) in VPC {self.vpc_id}.")

        if subnet_count == 100:
            print("Warning: more than 100 subnets found, only listing the first 100.")
        
        return subnets

    def list_security_groups(self, ec2_client):
        if not self.vpc_id:
            logging.error("list_security_groups() called without a VPC")
            return None

        print(f"Looking for existing security groups in VPC {self.vpc_id} ...")

        resp = None
        try:
            resp = ec2_client.describe_security_groups(
                Filters=[
                    {
                        'Name': 'vpc-id',
                        'Values': [
                            self.vpc_id,
                        ]
                    },
                ],
                MaxResults=100)
        except Exception as ex:
            logging.warning(f"Failed to list security groups: {ex}")
            print('We could not determine your existing security groups. Please check your AWS credentials and permissions.')
            return None

        security_groups = resp['SecurityGroups']
        security_group_count = len(security_groups)
        print(f"Found {security_group_count} security group(s) in VPC {self.vpc_id}.")

        if security_group_count == 100:
            print("Warning: more than 100 security groups found, only listing the first 100.")

        # Return the raw response data    
        return security_groups

    def list_run_environments(self):
        if not self.api_key:
            logging.error("API key not set, can't list Run Environments")
            return None

        response_ok = False
        response_status = None
        response_body = None
        page = None

        try:
            http = urllib3.PoolManager()
            r = http.request('GET', CLOUDREACTOR_API_BASE_URL + '/api/v1/run_environments/',
                             headers={
                                 'Authorization': f"Token {self.api_key}",
                                 'Accept': 'application/json'
                             }, timeout=10.0)

            response_status = r.status

            response_body = r.data.decode('utf-8')
            page = json.loads(response_body)

            response_ok = response_status == 200
        except urllib3.exceptions.HTTPError as http_error:
            print(f"An error communicating with cloudreactor.io occurred: {http_error}")

        if response_ok:
            return page['results']
        else:            
            if response_body:
                print(f"Got response status {response_status} and response body: {response_body} from the server")
            else:
                print(f"Got response status {response_status} from the server")

        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('--environment',
                        help='CloudReactor deployment environment')
    parser.add_argument('--log-level',
                        help=f"Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Defaults to {DEFAULT_LOG_LEVEL}.")

    args = parser.parse_args()

    deployment_environment = args.environment or 'production'
    
    if deployment_environment != 'production':
        print(f"Using deployment environment '{deployment_environment}'")

    log_level = (args.log_level or os.environ.get('WIZARD_LOG_LEVEL', DEFAULT_LOG_LEVEL)).upper()
    numeric_log_level = getattr(logging, log_level, None)
    if not isinstance(numeric_log_level, int):
        logging.warning(f"Invalid log level: {log_level}, defaulting to {DEFAULT_LOG_LEVEL}")
        numeric_log_level = getattr(logging, DEFAULT_LOG_LEVEL, None)

    logging.basicConfig(level=numeric_log_level,
                        format=f"%(levelname)s: %(message)s")
    print_banner()

    print("""    
Welcome to the CloudReactor AWS setup wizard!

This wizard can help you set up an ECS cluster and VPC suitable for running tasks in Docker 
containers using Fargate. You can also use it to enable CloudReactor to monitor and 
manage your tasks.

Tips:
- You can hit "Control-C" at any time to return to editing settings individually.
- When responding to questions, default answers are in square brackets, like [SOMEDEFAULT].
  Hitting enter will use the default answer.

""")

    logging.debug(f"CloudReactor Base URL = '{CLOUDREACTOR_API_BASE_URL}'")

    wizard = None

    if os.path.isfile(SAVED_STATE_FILENAME):
        try:
            with open(SAVED_STATE_FILENAME) as f:
                wizard = jsonpickle.decode(f.read())
                wizard.set_deployment_environment(deployment_environment)
        except Exception as ex:
            print("Couldn't read save file, starting over. Sorry about that!")
    else:
        print("No save file found, starting a new save file.")

    if wizard is None:
        wizard = Wizard(deployment=deployment_environment)

    wizard.run()
