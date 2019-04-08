import pycurl
import os
import sys
import requests
import json
import subprocess
from StringIO import StringIO
import logging
from urllib3._collections import HTTPHeaderDict
from wtforms import Form, StringField, PasswordField, validators

if sys.version_info.major == 2:
    from urlparse import urlsplit
else:
    from urllib.parse import urlsplit


def get_user_list(endpoint, id, secret, group):
    """Retrieve the access token.

    Exchange the access token with the given client id and secret.
    The refresh token in cached and the exchange token is kept in memory.

    .. todo::
        Add controls (aggiungi controlli)

    """

    logging.debug("Prepare header")

    data = {
        'client_id': id,
        'client_secret': secret,
        'grant_type': 'client_credentials', 'scope': 'scim:read'}

    logging.debug("Call get exchanged token with data: '%s'", str(data))

    response = requests.post(endpoint+"token", allow_redirects=True, data=data, verify=True)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        # Whoops it wasn't a 200
        logging.error("Error in get exchange token: %s", err)
        return response.status_code
    result = json.loads(response.content)
    logging.debug("Result: %s", result)

    d = HTTPHeaderDict()
    d.add('Authorization', 'Bearer '+str(result["access_token"]) )
    response = requests.get(endpoint+"scim/Groups", allow_redirects=True, headers=d, verify=True)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        # Whoops it wasn't a 200
        logging.error("Error in get the user list: %s", err)
        return response.status_code
    result = json.loads(response.content)

    userTuples = []
    for grp in result['Resources']:
        if grp['displayName'] == group:
            userTuples = [(x['display'], x['value']) for x in grp['members']]
            break

    return userTuples

def create_dn_from_userid(userid):
    userDN = "\/C\=IT\/O\=CLOUD@CNAF\/CN\={0}@dodas-iam".format(userid)
    return userDN

def register():

        iam_endpoint = os.getenv('IAM_ENDPOINT', default='https://dodas-iam.cloud.cnaf.infn.it/')
        client_id = os.getenv('CLIENT_ID', default='DUMMY')
        client_secret = os.getenv('CLIENT_SECRET', default='DUMMY')
        iam_group = os.getenv('IAM_GROUP', default='AMS')

        # TO DO: limit to one group!
        user_id_map = get_user_list(iam_endpoint, client_id, client_secret, iam_group)

        entries = []

        for username, userid in user_id_map:
            userDN = create_dn_from_userid(userid)
            logging.info("GSI \"^" + userDN.rstrip() + "$\"    " + username)
            entries.append("GSI \"^" + userDN.rstrip() + "$\"    " + username + "\n")

            command = "adduser {}".format(username)
            create_user = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True
            )

            _, err = create_user.communicate()

            if err:
                logging.error("failed to add user %s: %s", username, err)
            else:
                logging.info("Created user %s", username)

        with open('/home/uwdir/condormapfile', 'w+') as condor_file:
            condor_file.writelines(entries)

if __name__ == '__main__':
    logging.basicConfig(filename='/var/log/form/app.log',
                        format='[%(asctime)s][%(levelname)s][%(filename)s@%(lineno)d]->[%(message)s]',
                        level=logging.DEBUG)
    register()
