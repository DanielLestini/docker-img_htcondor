from flask import Flask, request, render_template
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


APP = Flask(__name__)


class RegistrationForm(Form):
    username = StringField('Username', [validators.Length(min=4, max=25)])
    token = PasswordField('IAM-Access-Token', [validators.DataRequired()])


def get_exchange_token(endpoint, audience, token, id, secret):
    """Retrieve the access token.

    Exchange the access token with the given client id and secret.
    The refresh token in cached and the exchange token is kept in memory.

    .. todo::
        Add controls (aggiungi controlli)

    """

    logging.debug("Prepare header")

    data = HTTPHeaderDict()
    data.add('grant_type', 'urn:ietf:params:oauth:grant-type:token-exchange')
    data.add('audience', audience)
    data.add('subject_token', token)
    data.add('scope', 'openid profile offline_access')

    logging.debug("Call get exchanged token with data: '%s'", str(data))

    response = requests.post(endpoint, data=data, auth=(id, secret), verify=True)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        # Whoops it wasn't a 200
        logging.error("Error in get exchange token: %s", err)
        return response.status_code
    result = json.loads(response.content)
    logging.debug("Result: %s", result)

    return result["access_token"]


@APP.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm(request.form)

    if request.method == 'POST' and form.validate():
        print(form.username.data,
              form.token.data)

        token = form.token.data

        audience = os.getenv('AUDIENCE', default='https://dodas-tts.cloud.cnaf.infn.it') 
        iam_token = os.getenv('IAM_TOKEN', default='https://dodas-iam.cloud.cnaf.infn.it/token')
        iam_tts_cred = os.getenv('IAM_TTS_CRED', default='https://dodas-tts.cloud.cnaf.infn.it/api/v2/iam/credential')
        iam_tts = os.getenv('IAM_TTS', default='https://dodas-tts.cloud.cnaf.infn.it')
        client_id = os.getenv('CLIENT_ID', default='99f7152a-0550-4be6-8c55-8f27dcbe67e0')
        client_secret = os.getenv('CLIENT_SECRET', default='AIEx7S3vAiIKhinEPndgnEw61GHxMC0k-_4wiVXpLOhLokr97-wNK5PEgMZOpqfO6UkKVARyBb2lQ8i4Qdv_38o')

        # get exchange token
        exchange_token = get_exchange_token(iam_token,
                                            audience,
                                            token,
                                            client_id,
                                            client_secret)

        # get proxy
        data = json.dumps({"service_id": "x509"})

        logging.debug("Create headers and buffers")
        headers = StringIO()
        buffers = StringIO()

        logging.debug("Prepare CURL")
        curl = pycurl.Curl()
        # TODO: metti  tts url
        curl.setopt(pycurl.URL, bytes(iam_tts_cred))
        curl.setopt(pycurl.HTTPHEADER, [
            'Authorization: Bearer {}'.format(
                str(exchange_token).split('\n', 1)[0]),
            'Content-Type: application/json'
        ])
        curl.setopt(pycurl.POST, 1)
        curl.setopt(pycurl.POSTFIELDS, data)
        curl.setopt(curl.WRITEFUNCTION, buffers.write)
        curl.setopt(curl.HEADERFUNCTION, headers.write)
        curl.setopt(curl.VERBOSE, True)

        print str(exchange_token).split('\n', 1)[0] 

        try:
            logging.debug("Perform CURL call")
            curl.perform()
            status = curl.getinfo(curl.RESPONSE_CODE)
            logging.debug("Result status: %s", status)
            logging.debug("Close CURL")
            curl.close()
            logging.debug("Get body content")
            body = buffers.getvalue()
            logging.debug("Body: %s", body)

            if str(status) != "303":
                logging.error(
                    "On 'get redirected with curl': http error: %s", str(status))
                return False
        except pycurl.error as error:
            errno, errstr = error
            logging.error('A pycurl error n. %s occurred: %s', errno, errstr)
            return False

        logging.debug("Manage redirect")
        for item in headers.getvalue().split("\n"):
            if "location" in item:
                # Example item
                #   "location: https://watts-dev.data.kit.edu/api/v2/iam/credential_data/xxx"
                logging.debug("Item url: %s", item)
                url_path = urlsplit(item.strip().split()[1]).path

                redirect = iam_tts + url_path

                logging.debug("Redirect location: %s", redirect)
                headers = {'Authorization': 'Bearer ' +
                           exchange_token}
                response = requests.get(redirect, headers=headers)

                try:
                    response.raise_for_status()
                except requests.exceptions.HTTPError as err:
                    # Whoops it wasn't a 200
                    logging.error(
                        "Error in get certificate redirect: %s", str(err))
                    return False

                with open('/tmp/output.json', 'w') as outf:
                    outf.write(response.content)

                cur_certificate = json.loads(response.content)
                cert_id = cur_certificate['credential']['id']
                logging.debug("Certificate id: '%s'", cert_id)

            else:
                logging.error("No location in redirect response")

        cert_file = '/tmp/cert.pem'
        key_file = '/tmp/key.pem'
        pass_file = '/tmp/passw.txt'
        proxy_file = '/tmp/' + form.username.data
 
        # get subject
        logging.debug("Load json and prepare objects")
        with open('/tmp/output.json') as tts_data_file:
            tts_data = json.load(tts_data_file)

        with open(cert_file, 'w+') as cur_file:
            cur_file.write(
                str(tts_data['credential']['entries'][0]['value']))

        with open(key_file, 'w+') as cur_file:
            cur_file.write(
                str(tts_data['credential']['entries'][1]['value']))

        with open(pass_file, 'w+') as cur_file:
            cur_file.write(
                str(tts_data['credential']['entries'][2]['value']))

        try:
            logging.debug("Change user key mod")
            os.chmod(key_file, 0o600)
        except OSError as err:
            logging.error(
                    "Permission denied to chmod passwd file: %s", err)

        logging.debug("Generating proxy for %s", token)

        command = "grid-proxy-init -valid 160:00 -key {} -cert {} -out {} -pwstdin ".format(
            key_file, cert_file, proxy_file
        )
        with open(pass_file) as my_stdin:
            my_passwd = my_stdin.read()
        proxy_init = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True
        )

        logging.debug("Execute proxy")
        proxy_out, proxy_err = proxy_init.communicate(input=my_passwd)

        logging.debug("Proxy result: %s", proxy_init.returncode)
        if proxy_init.returncode > 0:
            logging.error("grid-proxy-init failed for token %s",
                          exchange_token)
            logging.error("grid-proxy-init failed stdout %s", proxy_out)
            logging.error("grid-proxy-init failed stderr %s", proxy_err)

        command = "voms-proxy-info --file {} --subject ".format(proxy_file)

        get_DN = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True
        )

        DN, err = get_DN.communicate()

        if err:
            logging.error("voms-proxy-info failed for token %s", exchange_token)
            logging.error("voms-proxy-info failed stdout %s", DN)
            logging.error("voms-proxy-info failed stderr %s", err)
        else:
            print DN.replace("/","\/").replace("=","\=")

        with open('/home/uwdir/condormapfile', 'a') as condor_file:
            entry = "GSI \"^" + DN.replace("/", "\/").replace("=", "\=").rstrip() + "$\"    " + form.username.data
            condor_file.write(entry)

        # condor_reconfig

        return render_template('success.html')
    return render_template('register.html', form=form)


if __name__ == '__main__':
    logging.basicConfig(filename='/var/log/form/app.log',
                        format='[%(asctime)s][%(levelname)s][%(filename)s@%(lineno)d]->[%(message)s]',
                        level=logging.DEBUG)
    APP.logger.setLevel(logging.DEBUG)
    # TODO: if env PORT, otherwise 8080
    port = os.getenv('WEBUI_PORT', default='48080')
    APP.run(host="0.0.0.0", port=int(port))
