import argparse
import json
import os
import logging
import jsonpickle
import urllib3

import boto3
from botocore.exceptions import ClientError

import questionary

DEFAULT_LOG_LEVEL = 'ERROR'
SAVED_STATE_FILENAME = 'saved_settings.json'
DEFAULT_PREFIX = ' (Default)'
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
        '3': ['aws_access_key', 'AWS access key'],
        '4': ['aws_secret_key', 'AWS secret key'],
        '5': ['aws_region', 'AWS region'],
        '6': ['cluster_name', 'AWS ECS Cluster'],
        '7': ['stack_name', 'CloudFormation stack name']
    }

    def __init__(self, deployment: str, cloudreactor_api_base_url: str):
        self.deployment_environment = deployment
        self.cloudreactor_api_base_url = self.cloudreactor_api_base_url
        self.run_environment_name = None
        self.api_key = None
        self.existing_run_environments = None
        self.aws_access_key = None
        self.aws_secret_key = None
        self.aws_region = None
        self.aws_account_id = None
        self.cluster_name = None
        self.stack_name = None
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

        print("All settings have been entered.")
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
            return False

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
        elif p == 'cluster_name':
            self.ask_for_cluster_name()
        elif p == 'stack_name':
            self.ask_for_stack_name()
        else:
            print(f"{n} is not a valid choice. Please try another choice. [{p}]")

    def ask_for_api_key(self):
        q = "What is your CloudReactor API key?"

        if self.api_key:
            q += f" [{self.api_key}]"

        self.api_key = questionary.text(q).ask() or self.api_key

        if not self.api_key:
            print("Skipping CloudReactor API key for now.")
            self.existing_run_environments = None
            self.save()
            return

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

        default_run_environment_name =  self.run_environment_name or self.cluster_name

        if default_run_environment_name:
            q += f" [{default_run_environment_name}]"

        self.run_environment_name = questionary.text(q).ask() or default_run_environment_name

        if self.run_environment_name:
            print(f"Using Run Environment '{self.run_environment_name}'.")
        else:
            print("Skipping Run Environment for now.")

        # TODO: Validate if it exists already

        self.save()

    def ask_for_cluster_name(self):
        q = 'What is the name of the ECS cluster that will run your tasks?'

        default_cluster_name = self.cluster_name or self.stack_name

        if default_cluster_name:
            q += f"_{default_cluster_name}"

        self.cluster_name = questionary.text(q).ask() or default_cluster_name

        print(f"Using ECS cluster '{self.cluster_name}'.")

        self.save()

    def ask_for_aws_access_key(self):
        q = 'What AWS access key do you want to use. Type "none" to use the default permissions on this machine.'

        if self.aws_access_key:
            q += f" [{self.aws_access_key}]"

        self.aws_access_key = questionary.text(q).ask() or self.aws_access_key
        self.validate_aws_access()

    def ask_for_aws_secret_key(self):
        q = 'What AWS secret key do you want to use. Type "none" to use the default permissions on this machine.'

        if self.aws_secret_key:
            q += f" [{self.aws_secret_key}]"

        self.aws_secret_key = questionary.text(q).ask() or self.aws_secret_key
        self.validate_aws_access()

    def ask_for_aws_region(self):
        default_aws_region = self.aws_region or os.environ.get('AWS_REGION') or \
                             os.environ.get('AWS_DEFAULT_REGION') or DEFAULT_AWS_REGION

        self.aws_region = questionary.select(f"Which AWS region will you run ECS tasks?",
            choices=[default_aws_region + DEFAULT_PREFIX] + AWS_REGIONS).ask().replace(
            DEFAULT_PREFIX, '')

        print(f"Using AWS region {wizard.aws_region}.")

        self.save()

    def ask_for_stack_name(self):
        default_stack_name = self.stack_name or self.make_default_stack_name()

        self.stack_name = questionary.text(
            f"What do you want to name the CloudFormation stack? [{default_stack_name}]").ask() or default_stack_name

        print(f"Stack will be named '{self.stack_name}'.")

        wizard.save()

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
            return

        try:
            caller_id = sts.get_caller_identity()
            self.aws_account_id = caller_id['Account']
            print(f"Your AWS credentials for AWS account {self.aws_account_id} are valid.")
        except Exception as ex:
            logging.warning("Failed to get caller identity from AWS", exc_info=True)
            print("Failed to fetch your AWS user info. Please check your AWS credentials and try again.\n")
            self.aws_account_id = None

        self.save()

    def make_boto_client(self, service_name: str):
        if self.aws_access_key and self.aws_secret_key:
           return boto3.client(service_name,
                               aws_access_key_id=self.aws_access_key,
                               aws_secret_access_key=self.aws_secret_key)

        # TODO: use default credentials
        return None


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
        wizard = Wizard(deployment=deployment_environment,
                        cloudreactor_api_base_url=cloudreactor_api_base_url)

    wizard.run()
