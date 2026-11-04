# SPDX-License-Identifier: MIT
"""Administrator presets only; signed completion payloads, no redirects."""
import hashlib
import hmac
import os
import time
from urllib.request import HTTPRedirectHandler,Request,build_opener

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def send(preset,delivery_id,body):
    timestamp=str(int(time.time()))
    secret=os.environ[preset['secret_env']].encode()
    signature=hmac.new(secret,timestamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
    request=Request(preset['url'],data=body,method='POST',headers={'Content-Type':'application/json',
        'X-PuryF-Delivery':delivery_id,'X-PuryF-Timestamp':timestamp,'X-PuryF-Signature':'sha256='+signature})
    with build_opener(NoRedirect()).open(request,timeout=5) as response:return 200<=response.status<300
