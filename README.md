# cloudreactor-aws-setup-wizard

<p>
  <img alt="GitHub Workflow Status"
   src="https://img.shields.io/github/workflow/status/CloudReactor/cloudreactor-aws-setup-wizard/CI">
  <img
   src="https://img.shields.io/github/license/CloudReactor/cloudreactor-aws-setup-wizard.svg?style=flat-square"
   alt="License">
</p>

A command-line wizard to setup customer environments for running tasks,
optionally managed by CloudReactor

## What this can do (pick and choose any or all):

* Create a VPC, subnets, and a security group for running ECS Fargate tasks
* Create an ECS cluster
* Give permissions to CloudReactor to monitor and manage your ECS tasks
* Create or update Run Environments in CloudReactor so it knows how to run your ECS tasks

## Running the wizard

### Using Docker

Docker is the recommended way to run the wizard, since it removes the need to
install dependencies.

To start, if you haven't already, install Docker Compose on Linux, or
Docker Desktop on macOS or Windows.

Once installed, run the Docker daemon.

Next, create a directory somewhere that the wizard can use to save your
settings, between runs. For example,

    mkdir -p saved_state

Finally run the image:

    docker run --rm -it -v $PWD/saved_state:/usr/app/saved_state cloudreactor/aws-setup-wizard

which will use the saved_state subdirectory of the current directory to
save settings.

### Without Docker (native execution)

First install native python 3.11.x or above. Then clone this repo.
In a terminal window, navigate to the repo. Then:

    pip install -r requirements.txt
    python -m cloudreactor_aws_setup_wizard

Or with pipx:

    pipx run cloudreactor_aws_setup_wizard

## Permissions required / granting access

So that this wizard can create AWS resources for you, it needs the following
permissions:

* Upload CloudFormation stacks
* Create IAM Roles
* List ECS clusters, VPCs, subnets, NAT gateways, Elastic IPs, and security
groups
* Create ECS clusters (if using the wizard to create an ECS cluster)
* Create VPCs, subnets, internet gateways, NAT gateways, route tables,
route table associations, VPC endpoints, and security groups
(if using the wizard to create a VPC)

You can give the wizard these permissions in a few different ways:

1) An access key and access secret that you manually enter when prompted by
the wizard
2) Passing the access key and the secret key in the environment variables
`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` respectively when you
launch the wizard. If you are using Docker to run the wizard:

    ```
    docker run --rm -it -v $PWD/saved_state:/usr/app/saved_state -e AWS_ACCESS_KEY_ID=<access_key> -e AWS_SECRET_ACCESS_KEY=<secret_key> cloudreactor/aws-setup-wizard
    ```
3) Using your credentials saved in `~/.aws`:

    ```
    docker run --rm -it -v $PWD/saved_state:/usr/app/saved_state -v $HOME/.aws/:/root/.aws/ -e AWS_PROFILE=<profile_name> cloudreactor/aws-setup-wizard
    ```

    `-e AWS_PROFILE=<profile_name>` can be omitted if you just want to use your
    default AWS profile.

4) If run from an EC2 instance, the wizard should inherit permissions from
the EC2 instance role (not tested yet)

## Development

We use [poetry](https://python-poetry.org/) to manage dependencies, build, and publish this library.

To export the library dependencies:

    poetry export --output requirements.txt

To export the dev dependencies:

    poetry export --with dev --output dev-requirements.txt

To run possibly modified source code in development

**On Linux or macOS, run:**

    ./build.sh

(only needed the first time you get the source code, or whenever you update the source code from the repo)

and then

    ./wizard.sh

**On Windows, run:**

    .\build.cmd

(only needed the first time you get the source code, or whenever you update the source code from the repo)

and then

    .\wizard.cmd

## Acknowledgements

* [questionary](https://github.com/tmbo/questionary) for prompts
* [cloudonaut.io](https://github.com/widdix/aws-cf-templates) for a CloudFormation
template for creating a VPC
* [Text to ASCII Art Generator](patorjk.com) for the logo
