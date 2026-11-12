from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
from pathlib import Path
import sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib.archives import month_pib,yojana_issue,article

class handler(BaseHTTPRequestHandler):
 def do_GET(self):
  q=parse_qs(urlparse(self.path).query);action=q.get('action',[''])[0]
  try:
   if action=='health':result={'ok':True,'version':4,'mode':'stateless-vercel'}
   elif action=='month':
    year=int(q.get('year',['0'])[0]);month=int(q.get('month',['0'])[0])
    if not 2004<=year<=2100 or not 1<=month<=12:raise ValueError('Choose a valid archive month/year.')
    result=month_pib(year,month);result={**result,'month':f'{year}-{month:02d}','complete':True}
   elif action=='issue':result=yojana_issue(int(q.get('month',['0'])[0]),int(q.get('year',['0'])[0]))
   elif action=='article':result=article(q.get('id',[''])[0])
   else:return self.reply({'error':'Unknown archive action.'},400)
   return self.reply(result,200)
  except ValueError as e:return self.reply({'error':str(e)},422)
  except Exception as e:return self.reply({'error':'Official source retrieval did not complete. '+str(e)[:500]},502)
 def reply(self,result,status):
  raw=json.dumps(result,ensure_ascii=False).encode()
  if len(raw)>4000000:raw=json.dumps({'error':'The selected issue text exceeds the hosted response limit. Download the English PDF and load it with the browser PDF option.'}).encode();status=413
  self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
