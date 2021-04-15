from typing import cast, Any, Dict, Optional

import json
import os
import urllib3

import logging

CLOUDREACTOR_API_BASE_URL = os.environ.get('CLOUDREACTOR_API_BASE_URL',
    'https://api.cloudreactor.io')


class CloudReactorApiClient(object):
    def __init__(self, username: str, password: str) -> None:
        logging.debug(f"CloudReactor Base URL = '{CLOUDREACTOR_API_BASE_URL}'")

        self.username = username
        self.password = password
        self.access_token: Optional[str] = None
        self.http = urllib3.PoolManager()

    def authenticate(self):
        data = {
          'username': self.username,
          'password': self.password,
        }

        r = self.http.request('POST',
                CLOUDREACTOR_API_BASE_URL + '/auth/jwt/create/',
                body=json.dumps(data),
                headers={
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                }, timeout=10.0)

        response_status = cast(int, r.status)

        if (response_status >= 200) and (response_status < 300):
            response_body = cast(str, r.data.decode('utf-8'))
            response_data = json.loads(response_body)
            self.access_token = cast(str, response_data['access'])
        else:
            raise RuntimeError(f'Bad authentication response code: {response_status}')

    def make_authentication_header(self):
        if self.access_token is None:
            self.authenticate()

        return 'JWT ' + self.access_token

    def list_groups(self) -> Dict[str, Any]:
        return self.send_and_load_json('groups/')

    def create_group(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.send_and_load_json(path='groups/', method='POST', data=data)

    def list_run_environments(self, group_id: int) -> Dict[str, Any]:
        return self.send_and_load_json('run_environments/', params={
            'created_by_group__id': group_id
        })

    def create_run_environment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.create_or_update_run_environment(None, data)

    def update_run_environment(self, uuid: str,
            data: Dict[str, Any]) -> Dict[str, Any]:
        return self.create_or_update_run_environment(uuid, data)

    def create_or_update_run_environment(self, uuid: Optional[str],
            data: Dict[str, Any]) -> Dict[str, Any]:
        path = 'run_environments/'
        method = 'POST'
        if uuid:
            path += uuid + '/'
            method = 'PATCH'

        return self.send_and_load_json(path=path, method=method, data=data)

    def send_and_load_json(self, path: str, method: str = 'GET',
            params: Optional[Dict[str, Any]] = None,
            data: Optional[Dict[str, Any]] = None) -> Any:
        headers = {
            'Authorization': self.make_authentication_header(),
            'Accept': 'application/json'
        }

        body = None
        if data is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(data)

        r = self.http.request(method,
                CLOUDREACTOR_API_BASE_URL + '/api/v1/' + path,
                fields=params,
                headers=headers, body=body, timeout=10.0)

        response_status = r.status
        response_body = r.data.decode('utf-8')

        if (response_status >= 200) and (response_status < 300):
            return json.loads(response_body)
        else:
            message = ''
            if response_body:
                message = f"Got response status {response_status} and response body: {response_body} from the server"
            else:
                message = f"Got response status {response_status} from the server"

            raise RuntimeError(message)



if __name__ == '__main__':
    client = CloudReactorApiClient(
            username=os.environ['CLOUDREACTOR_USERNAME'],
            password=os.environ['CLOUDREACTOR_PASSWORD'])

    groups = client.list_groups()['results']

    print(f"{groups=}")

    if len(groups) == 0:
        print('No groups found, not listing Run Environments.');

    run_environments = client.list_run_environments(groups[0]['id'])

    print(f"{run_environments=}")
