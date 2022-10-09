# Alpine base image can lead to long compilation times and errors.
# https://pythonspeed.com/articles/base-image-python-docker-images/
FROM python:3.9.14-slim-buster

LABEL maintainer="jeff@cloudreactor.io"

WORKDIR /usr/app

RUN pip install --no-input --no-cache-dir --upgrade pip==22.2.2
RUN pip install --no-input --no-cache-dir pip-tools==6.9.0 requests==2.28.1

COPY requirements.in .
COPY requirements.txt .

RUN pip-compile --allow-unsafe --generate-hashes \
  requirements.in --output-file requirements.txt

# install dependencies
# https://stackoverflow.com/questions/45594707/what-is-pips-no-cache-dir-good-for
RUN pip install --no-input --no-cache-dir -r requirements.txt

# Output directly to the terminal to prevent logs from being lost
# https://stackoverflow.com/questions/59812009/what-is-the-use-of-pythonunbuffered-in-docker-file
ENV PYTHONUNBUFFERED 1

# Don't write *.pyc files
ENV PYTHONDONTWRITEBYTECODE 1

# Enable the fault handler for segfaults
# https://docs.python.org/3/library/faulthandler.html
ENV PYTHONFAULTHANDLER 1

ENV PYTHONPATH /usr/app/src

RUN mkdir ./saved_state
COPY banner.txt ./
COPY wizard_config.yml ./
COPY templates ./templates
COPY src ./src

ENTRYPOINT ["python", "src/wizard.py"]
