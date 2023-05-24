import argparse
import logging
import os

import jsonpickle

from .wizard import SAVED_STATE_DIRECTORY, SAVED_STATE_FILENAME, Wizard

DEFAULT_LOG_LEVEL = "ERROR"

BANNER = r"""
           ________                ______                  __
          / ____/ /___  __  ______/ / __ \___  ____ ______/ /_____  _____
         / /   / / __ \/ / / / __  / /_/ / _ \/ __ `/ ___/ __/ __ \/ ___/
        / /___/ / /_/ / /_/ / /_/ / _, _/  __/ /_/ / /__/ /_/ /_/ / /
        \____/_/\____/\__,_/\__,_/_/ |_|\___/\__,_/\___/\__/\____/_/
  ____       _     __     ______           __    _      ___                __
 / __ \__ __(_____/ /__  / __/ /____ _____/ /_  | | /| / (_______ ________/ /
/ /_/ / // / / __/  '_/ _\ \/ __/ _ `/ __/ __/  | |/ |/ / /_ / _ `/ __/ _  /
\___\_\_,_/_/\__/_/\_\ /___/\__/\_,_/_/  \__/   |__/|__/_//__\_,_/_/  \_,_/
"""


def run():
    parser = argparse.ArgumentParser()

    parser.add_argument("--api-base-url", help="CloudReactor API base URL")
    parser.add_argument("--environment", help="CloudReactor deployment environment")
    parser.add_argument(
        "--log-level",
        help=f"Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Defaults to {DEFAULT_LOG_LEVEL}.",
    )

    args = parser.parse_args()

    api_base_url = args.api_base_url

    cloudreactor_deployment_environment = args.environment or "production"

    if cloudreactor_deployment_environment != "production":
        print(
            f"Using CloudReactor deployment environment '{cloudreactor_deployment_environment}'"
        )

    log_level = (
        args.log_level or os.environ.get("WIZARD_LOG_LEVEL", DEFAULT_LOG_LEVEL)
    ).upper()
    numeric_log_level = getattr(logging, log_level, None)
    if not isinstance(numeric_log_level, int):
        logging.warning(
            f"Invalid log level: {log_level}, defaulting to {DEFAULT_LOG_LEVEL}"
        )
        numeric_log_level = getattr(logging, DEFAULT_LOG_LEVEL, None)

    logging.basicConfig(level=numeric_log_level, format="%(levelname)s: %(message)s")
    print(BANNER)

    print(
        """
Welcome to the CloudReactor AWS setup wizard!

This wizard can help you set up an ECS cluster and VPC suitable for running tasks in Docker
containers using Fargate. You can also use it to enable CloudReactor to monitor and
manage your tasks.

Tips:
- You can hit "Control-C" at any time to return to editing settings individually.
- When responding to questions, default answers are in square brackets, like [SOMEDEFAULT].
  Hitting enter will use the default answer.

"""
    )

    wizard = None

    if os.path.isfile(SAVED_STATE_FILENAME):
        try:
            with open(SAVED_STATE_FILENAME) as f:
                wizard = jsonpickle.decode(f.read())
                wizard.set_options(
                    api_base_url=api_base_url,
                    cloudreactor_deployment_environment=cloudreactor_deployment_environment,
                )
        except Exception:
            print("Couldn't read save file, starting over. Sorry about that!")
    else:
        print("No save file found, starting a new save file.")

        if not os.path.isdir(SAVED_STATE_DIRECTORY):
            os.makedirs(SAVED_STATE_DIRECTORY, exist_ok=True)

    if wizard is None:
        wizard = Wizard(
            api_base_url=api_base_url,
            cloudreactor_deployment_environment=cloudreactor_deployment_environment,
        )

    wizard.run()


if __name__ == "__main__":
    run()
