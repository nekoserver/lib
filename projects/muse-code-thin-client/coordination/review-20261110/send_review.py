"""Send this recorded discussion once; never retry an uncertain dispatch."""
import datetime, http.client, json, os, socket, subprocess, time, urllib.request
from pathlib import Path
HERE = Path(__file__).resolve().parent
ENTRY = 'muse-code-wasm-thin-client-20261110-e2'
URL = 'https://api.cloudflare.com/client/v4/accounts/' + os.environ['CLOUDFLARE_ACCOUNT_ID'] + '/d1/database/ab65ff96-6333-4673-9ad4-4324be622184/query'
def d1(sql, params):
    request = urllib.request.Request(URL, data=json.dumps({'sql':sql,'params':params}).encode(), headers={'Authorization':'Bearer '+os.environ['CF_CONTAINER_API_TOKEN'],'Content-Type':'application/json'}, method='POST')
    with urllib.request.urlopen(request,timeout=25) as response: data=json.load(response)
    if not data.get('success'): raise RuntimeError('Board update failed')
    return data['result'][0]
class Tailnet(http.client.HTTPConnection):
    def connect(self):
        self.sock,remote=socket.socketpair();self.sock.settimeout(120)
        with remote:self.nc=subprocess.Popen(['tailscale','nc','muse-vm','8080'],stdin=remote,stdout=remote,stderr=subprocess.DEVNULL)
    def close(self):
        super().close()
        if hasattr(self,'nc'):self.nc.kill();self.nc.wait()
claim=d1("UPDATE inquiry_entries SET status='sent' WHERE id=? AND status='planned'",[ENTRY])
if claim.get('meta',{}).get('changes')!=1:raise SystemExit('Entry already dispatched; no automatic resend')
started=time.monotonic();state={'entry_id':ENTRY,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'state':'sent','scope':'discussion_only'}
(HERE/'status.json').write_text(json.dumps(state,indent=2)+'\n')
c=Tailnet('muse-vm',8080,timeout=120)
try:
    body=json.dumps({'model':'muse','messages':[{'role':'user','content':(HERE/'request.md').read_text()}]})
    c.request('POST','/v1/chat/completions',body,{'Authorization':'Bearer '+Path('/etc/lib-muse-api-key').read_text().strip(),'Content-Type':'application/json'})
    response=c.getresponse();raw=response.read(1_048_577)
    if response.status!=200 or len(raw)>1_048_576:raise RuntimeError('upstream_response_unconfirmed')
    reply=json.loads(raw)['choices'][0]['message']['content']
    if not isinstance(reply,str) or not reply.strip():raise RuntimeError('empty_response')
    (HERE/'response.md').write_text(reply+'\n')
    state.update(state='answered',http_status=200)
    d1("UPDATE inquiry_entries SET answer=?,status='answered',duration_seconds=? WHERE id=? AND status='sent'",[reply,int(time.monotonic()-started),ENTRY])
    print('HTTP 200\n'+reply)
except Exception as error:
    state.update(state='delivery_unknown',error=type(error).__name__)
    d1("UPDATE inquiry_entries SET status='failed',error=?,duration_seconds=? WHERE id=? AND status='sent'",['response_unconfirmed_'+type(error).__name__,int(time.monotonic()-started),ENTRY])
    print('Discussion response unconfirmed:',type(error).__name__)
finally:
    c.close();state['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();(HERE/'status.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
