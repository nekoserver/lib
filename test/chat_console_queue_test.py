"""Codex 0.166.0 native thread queue contract, no fork or writer takeover.
Source: https://learn.chatgpt.com/docs/cli/reference#codex-queue
Wire fields checked against 0.166.0 app-server generate-json-schema --experimental.
"""
import asyncio,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from websockets.asyncio.server import unix_serve
sys.path.insert(0,str(Path(__file__).parents[1]/'ops'))
import chat_observer as observer

class QueueInputTest(unittest.IsolatedAsyncioTestCase):
 async def exercise(self,invalid=False,queue_error=False):
  calls=[]
  async def server(ws):
   async for raw in ws:
    d=json.loads(raw)
    if 'id' not in d:continue
    calls.append(d)
    method=d['method'];result={}
    if method=='thread/read':result={'thread':{'id':'fixed-thread','status':{'type':'notLoaded'}}}
    if method=='thread/resume':
     await ws.send(json.dumps({'id':d['id'],'error':{'message':'thread fixed-thread already has an active writer'}}));continue
    if method=='thread/queue/add':
     if queue_error:
      await ws.send(json.dumps({'id':d['id'],'error':{'message':'queue unavailable'}}));continue
     p=d['params'];self.assertEqual(p['threadId'],'fixed-thread')
     self.assertEqual(p['input'],[{'type':'text','text':'hello','text_elements':[]}])
     self.assertTrue(p['clientUserMessageId'])
     result={'queuedSubmission':{'id':'queued-1','clientUserMessageId':p['clientUserMessageId'],'input':p['input']}}
     if invalid:result['queuedSubmission']['clientUserMessageId']='different-client'
    await ws.send(json.dumps({'id':d['id'],'result':result}))
  with tempfile.TemporaryDirectory() as tmp:
   async with unix_serve(server,tmp+'/app.sock'):
    if invalid or queue_error:
     with self.assertRaises(ValueError):await observer.send_to_console(tmp+'/app.sock','fixed-thread','hello')
     outcome=None
    else:outcome=await observer.send_to_console(tmp+'/app.sock','fixed-thread','hello')
  methods=[c['method'] for c in calls]
  self.assertEqual(methods.count('thread/queue/add'),1)
  self.assertNotIn('turn/start',methods);self.assertNotIn('thread/fork',methods)
  return outcome,calls

 async def test_owned_thread_queues_once_to_same_thread(self):
  outcome,calls=await self.exercise()
  self.assertEqual(outcome,{'queued':True})
  self.assertEqual([c['method'] for c in calls],['initialize','thread/read','thread/resume','thread/queue/add'])
  self.assertTrue(calls[0]['params']['capabilities']['experimentalApi'])

 async def test_invalid_queue_ack_is_not_accepted(self):await self.exercise(invalid=True)
 async def test_queue_failure_is_not_accepted_or_retried(self):await self.exercise(queue_error=True)

 async def test_observation_cannot_enqueue(self):
  from unittest.mock import AsyncMock
  client=observer.ReadClient(AsyncMock())
  with self.assertRaises(ValueError):await client.request('thread/queue/add',{})

if __name__=='__main__':unittest.main(verbosity=2)
