# cloudreactor-aws-setup-wizard

A command-line wizard to setup customer environments for running tasks managed by CloudReactor

## What this can do (pick and choose any or all):

* Create a VPC, subnets, and a security group for running ECS Fargate tasks
* Create an ECS cluster
* Give permissions to CloudReactor to monitor and manage your ECS tasks
* Create or update Run Environments in CloudReactor so it knows how to run your ECS tasks

## Permissions required

To allow this wizard to create AWS resources for you, it needs an AWS access key.
The access key needs to be associated with a user that has the following permissions to:

* Upload CloudFormation stacks
* Create IAM Roles
* List ECS clusters, VPCs, subnets, NAT gateways, Elastic IPs, and security
groups
* Create ECS clusters (if using the wizard to create an ECS cluster)
* Create VPCs, subnets, internet gateways, NAT gateways, route tables,
route table associations, VPC endpoints, and security groups
(if using the wizard to create a VPC)

The access key and secret key are not sent to CloudReactor.

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

First install native python 3.9.x or above. Then clone this repo.
In a terminal window, navigate to the repo. Then:

    pip install -r requirements.txt
    python src/wizard.py

## Development

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
