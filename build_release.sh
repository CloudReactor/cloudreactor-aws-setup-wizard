#!/bin/bash
# This script builds the image for releasing into Docker Hub, and is not needed
# unless you're developing this project.

set -e

docker build -t aws-ecs-setup-wizard -t \
 cloudreactor/aws-ecs-setup-wizard .

# docker login
# docker tag aws-ecs-setup-wizard cloudreactor/aws-ecs-setup-wizard:1.0.0
# docker push cloudreactor/aws-ecs-setup-wizard:1.0.0