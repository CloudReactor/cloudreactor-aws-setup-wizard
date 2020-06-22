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
* Upload CloudFormation stack
* Create IAM Roles
* List ECS clusters, VPCs, subnets, and security groups
* Create ECS clusters (if using the wizard to create an ECS cluster)
* Create VPCs, subnets, internet gateways, and security groups (if using the wizard to create a VPC)

The access key and secret key are not sent to CloudReactor.

## Running

With Docker Compose on Linux or MacOS:

    ./wizard.sh

With Docker Desktop for Windows:

    .\wizard.bat

With native python 3.8+:

    pip install -r requirements.txt
    python src/wizard.py

## Acknowledgments

* [cloudonaut.io](https://github.com/widdix/aws-cf-templates) for a CloudFormation
template for creating a VPC
* [Text to ASCII Art Generator](patorjk.com) for the logo
