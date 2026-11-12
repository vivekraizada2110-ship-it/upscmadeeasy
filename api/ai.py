"""Fixed-destination, no-key-storage AI proxy for same-origin workspaces.
No API credentials or prompts are written to disk, cached or logged by this code.
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse
import json,re,requests

BASES={
 'gemini':'https://generativelanguage.googleapis.com/v1beta',
 'openrouter':'https://openrouter.ai/api/v1',
 'xai':'https://api.x.ai/v1',
 'groq':'https://api.groq.com/openai/v1',
 'deepseek':'https://api.deepseek.com',
 'anthropic':'https://api.anthropic.com/v1',
 'openai':'https://api.openai.com/v1'}

def clean_schema(value):
 if isinstance(value,list):return [clean_schema(x) for x in value]
 if not isinstance(value,dict):return value
 out={k:clean_schema(v) for k,v in value.items() if k not in ['propertyOrdering']}
 if isinstance(out.get('type'),str):out['type']=out['type'].lower()
 return out

def messages_from(payload):
 system=payload.get('systemInstruction') or payload.get('system_instruction') or {}
 sy='\n'.join(x.get('text','') for x in system.get('parts',[]))
 cfg=payload.get('generationConfig') or {};schema=cfg.get('responseSchema') or cfg.get('responseJsonSchema')
 if schema:sy+='\nReturn ONLY valid JSON that satisfies this JSON schema. Do not add markdown fences:\n'+json.dumps(clean_schema(schema),ensure_ascii=False)
 elif cfg.get('responseMimeType')=='application/json':sy+='\nReturn ONLY valid JSON. Do not add markdown fences or commentary.'
 messages=[]
 if sy:messages.append({'role':'system','content':sy})
 for c in payload.get('contents',[]):
  parts=[]
  for part in c.get('parts',[]):
   if 'text' in part:parts.append({'type':'text','text':str(part['text'])})
   inline=part.get('inlineData') or part.get('inline_data')
   if inline:
    mime=inline.get('mimeType') or inline.get('mime_type') or 'image/jpeg'
    if mime not in ['image/png','image/jpeg','image/webp','image/gif']:raise ValueError('This selected provider adapter accepts page images, not raw PDF inputs. Extract text or render selected PDF pages first.')
    parts.append({'type':'image_url','image_url':{'url':'data:'+mime+';base64,'+inline.get('data','')}})
  if parts:
   content=parts[0]['text'] if len(parts)==1 and parts[0]['type']=='text' else parts
   messages.append({'role':'assistant' if c.get('role')=='model' else 'user','content':content})
 if not messages:raise ValueError('No prompt content supplied.')
 return messages,cfg

def perform(data,key,client=requests):
 provider=data.get('provider');model=str(data.get('model') or '').strip();action=data.get('action','generate')
 if provider not in BASES:raise ValueError('Unknown provider.')
 if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,180}',model):raise ValueError('Invalid model ID.')
 if not key or len(key)<10 or re.search(r'\s',key):raise ValueError('Missing or incomplete provider API key.')
 base=BASES[provider];headers={'Content-Type':'application/json'}
 if provider=='gemini':headers['x-goog-api-key']=key
 elif provider=='anthropic':headers.update({'x-api-key':key,'anthropic-version':'2023-06-01'})
 else:headers['Authorization']='Bearer '+key
 if provider=='openrouter':headers['X-Title']='Conquer UPSC Workspace'
 if action=='models':
  if provider=='gemini':
   names=[];token=''
   for _ in range(8):
    resp=client.get(base+'/models',headers=headers,params={'pageSize':200,**({'pageToken':token} if token else {})},timeout=35)
    body=resp.json()
    if not resp.ok:return resp.status_code,body,resp.headers
    names.extend(str(x['name']).removeprefix('models/') for x in body.get('models',[]) if 'generateContent' in x.get('supportedGenerationMethods',[]))
    token=body.get('nextPageToken','')
    if not token:break
   return 200,{'models':list(dict.fromkeys(names))},{}
  resp=client.get(base+'/models',headers=headers,timeout=45);body=resp.json()
  if not resp.ok:return resp.status_code,body,resp.headers
  entries=body.get('data') or body.get('models') or []
  names=[str(x.get('id') or x.get('name') or '') for x in entries]
  return 200,{'models':[n for n in names if n]},{}
 if action!='generate':raise ValueError('Unknown AI action.')
 payload=data.get('payload')
 if not isinstance(payload,dict):raise ValueError('Invalid prompt payload.')
 if provider=='gemini':
  # Preserve all original schemas/images and the user's exact model ID.
  resp=client.post(base+'/models/'+model+':generateContent',headers=headers,json=payload,timeout=115)
  return resp.status_code,resp.json(),resp.headers
 messages,cfg=messages_from(payload)
 if provider=='anthropic':
  systems=[m['content'] for m in messages if m['role']=='system'];translated=[]
  for m in messages:
   if m['role']=='system':continue
   content=m['content']
   if isinstance(content,list):
    transformed=[]
    for part in content:
     if part['type']=='text':transformed.append(part)
     elif part['type']=='image_url':
      prefix,encoded=part['image_url']['url'].split(',',1)
      transformed.append({'type':'image','source':{'type':'base64','media_type':prefix[5:].split(';')[0],'data':encoded}})
    content=transformed
   translated.append({'role':m['role'],'content':content})
  req={'model':model,'system':'\n'.join(systems),'messages':translated,'max_tokens':min(int(cfg.get('maxOutputTokens',8192)),32768)}
  resp=client.post(base+'/messages',headers=headers,json=req,timeout=115);body=resp.json()
  if not resp.ok:return resp.status_code,body,resp.headers
  text=''.join(x.get('text','') for x in body.get('content',[]) if x.get('type')=='text')
  finish='MAX_TOKENS' if body.get('stop_reason')=='max_tokens' else 'STOP'
  usage=body.get('usage',{})
  return 200,{'candidates':[{'content':{'parts':[{'text':text}]},'finishReason':finish}], 'usageMetadata':{'promptTokenCount':usage.get('input_tokens',0),'candidatesTokenCount':usage.get('output_tokens',0)}},{}
 req={'model':model,'messages':messages,'stream':False,'max_tokens':min(int(cfg.get('maxOutputTokens',8192)),32768)}
 if provider not in ['xai']:req['temperature']=cfg.get('temperature',0.35)
 # Do not force response_format on endpoints that do not support it. Schemas are included in instructions,
 # and original client-side validators still reject malformed results; nothing is silently accepted.
 resp=client.post(base+'/chat/completions',headers=headers,json=req,timeout=115);body=resp.json()
 if not resp.ok or body.get('error'):return resp.status_code if not resp.ok else int(body['error'].get('code',502)),body,resp.headers
 choice=(body.get('choices') or [{}])[0];msg=choice.get('message') or {};content=msg.get('content','')
 text=''.join(x.get('text','') for x in content if isinstance(x,dict)) if isinstance(content,list) else str(content or '')
 finish='MAX_TOKENS' if choice.get('finish_reason') in ['length','max_tokens'] else 'STOP';usage=body.get('usage',{})
 return 200,{'candidates':[{'content':{'parts':[{'text':text}]},'finishReason':finish}], 'usageMetadata':{'promptTokenCount':usage.get('prompt_tokens',0),'candidatesTokenCount':usage.get('completion_tokens',0)}},{}

class handler(BaseHTTPRequestHandler):
 def do_POST(self):
  key=''
  try:
   origin=self.headers.get('Origin');host=self.headers.get('X-Forwarded-Host') or self.headers.get('Host')
   if origin and urlparse(origin).netloc!=host:return self.reply({'error':{'message':'Cross-origin requests are not allowed.'}},403)
   n=int(self.headers.get('Content-Length',0))
   if n<=0 or n>4000000:return self.reply({'error':{'message':'Request exceeds the hosted limit. Send fewer page images.'}},413)
   data=json.loads(self.rfile.read(n));key=self.headers.get('Authorization','').removeprefix('Bearer ').strip()
   status,body,extra=perform(data,key)
   # Only pass retry guidance and normalized JSON. No provider or user headers are logged/stored.
   if status>=400:
    message=body.get('error',{}).get('message') if isinstance(body.get('error'),dict) else str(body.get('error') or body.get('message') or 'Provider request failed.')
    body={'error':{'message':str(data.get('provider'))+' HTTP '+str(status)+': '+str(message).replace(key,'[redacted]')[:1200]}}
   return self.reply(body,status,extra.get('Retry-After'))
  except ValueError as e:return self.reply({'error':{'message':str(e).replace(key,'[redacted]') if key else str(e)}},400)
  except requests.Timeout:return self.reply({'error':{'message':'Provider request timed out. Completed study data is retained.'}},504)
  except Exception:return self.reply({'error':{'message':'The provider proxy could not complete this request. Check your connection or server logs; do not share your API key.'}},502)
 def reply(self,obj,status,retry=None):
  raw=json.dumps(obj,ensure_ascii=False).encode()
  if len(raw)>4000000:raw=json.dumps({'error':{'message':'Provider response exceeded the hosted limit. Use a smaller selection.'}}).encode();status=413
  self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)))
  if retry:self.send_header('Retry-After',str(retry))
  self.end_headers();self.wfile.write(raw)
