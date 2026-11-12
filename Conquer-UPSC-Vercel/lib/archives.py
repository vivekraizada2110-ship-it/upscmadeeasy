from urllib.parse import urljoin, unquote
from datetime import date, datetime, timedelta
import calendar, re, time
import requests
from bs4 import BeautifulSoup
import pymupdf
CACHE={}
PIB='https://www.pib.gov.in/Allrel.aspx?reg=3&lang=1'
YBASE='https://www.publicationsdivision.nic.in/journals/'
YARCH=YBASE+'index.php?route=page/ajkalarchives&cid=2&lang=English&year='
def session():
 s=requests.Session(); s.headers['User-Agent']='Mozilla/5.0 ConquerWorkspace/4'
 from requests.adapters import HTTPAdapter
 from urllib3.util.retry import Retry
 # Archive requests only read public data. Retry brief connection/DNS failures,
 # but do not turn slow reads into an unbounded serverless job.
 retry=Retry(total=2,connect=2,read=0,status=1,backoff_factor=.5,status_forcelist=[502,503,504],allowed_methods=['GET','POST'],respect_retry_after_header=False)
 s.mount('https://',HTTPAdapter(max_retries=retry));return s

def english(text):
 # English releases may quote a Hindi event name; reject Hindi-dominant text, not proper nouns.
 return len(re.findall('[A-Za-z]',text))>3*len(re.findall('[\u0900-\u097f]',text))

def month_pib(year, month):
 key=('pib',year,month)
 if key in CACHE and time.time()-CACHE[key][0]<900:return CACHE[key][1]
 s=session(); r=s.get(PIB,timeout=75);r.raise_for_status();p=BeautifulSoup(r.content,'html.parser')
 data={x['name']:x.get('value','') for x in p.select('input[name]') if x.get('type') not in ('submit','button')}
 for sel in p.select('select[name]'):
  opt=sel.select_one('option[selected]') or sel.select_one('option');data[sel['name']]=opt.get('value','') if opt else ''
 fields={'ddlday':'0','ddlMonth':str(month),'ddlYear':str(year),'ddlMinistry':'0'}
 for k in list(data):
  for suffix,val in fields.items():
   if k.endswith('$'+suffix):data[k]=val
 data['ctl00$Bar1$ddlLang']='1';data['ctl00$Bar1$ddlregion']='3';data['__EVENTTARGET']='ctl00$ContentPlaceHolder1$ddlMonth'
 r=s.post(PIB,data=data,timeout=75);r.raise_for_status();p=BeautifulSoup(r.content,'html.parser')
 for suffix,val in fields.items():
  select=p.find('select',attrs={'name':re.compile(re.escape('$'+suffix)+'$')})
  chosen=select.select_one('option[selected]') if select else None
  if not chosen or chosen.get('value')!=val:raise ValueError('PIB did not apply archive filter '+suffix+'; refusing to show current-day results as an archive.')
 selected=p.select_one('#Bar1_ddlLang option[selected]')
 if not selected or selected.get('value')!='1':raise ValueError('PIB did not return English.')
 out=[]; seen=set(); undated=0; language_rejected=0
 for a in p.select('a[href*="PRID="]'):
  li=a.find_parent('li');stamp=li.select_one('.publishdatesmall') if li else None
  if not stamp:continue
  text=stamp.get_text(' ',strip=True);match=re.search(r'(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})',text)
  if not match:undated+=1;continue
  day,mon,yr=match.groups()
  try:dt=datetime.strptime(f'{day} {mon[:3]} {yr}','%d %b %Y').date()
  except ValueError:undated+=1;continue
  if (dt.year,dt.month)!=(year,month):raise ValueError('PIB returned an out-of-month release; archive validation failed.')
  title=a.get_text(' ',strip=True);prid=re.search(r'PRID=(\d+)',a['href']).group(1)
  if prid in seen:continue
  if not english(title):language_rejected+=1;continue
  seen.add(prid)
  out.append({'id':prid,'title':title,'date':dt.isoformat(),'link':f'https://www.pib.gov.in/PressReleaseDetail.aspx?PRID={prid}&reg=3&lang=1','source':'pib'})
 advertised=re.search(r'Displaying\s+(\d+)\s+Press Releases',p.get_text(' ',strip=True))
 count=int(advertised.group(1)) if advertised else None
 if undated or language_rejected:raise ValueError(f'Archive contained {undated} undated and {language_rejected} non-English rows; refusing to claim full coverage.')
 if count is None or count!=len(out):raise ValueError(f'PIB advertised {count} releases, but {len(out)} dated English rows were parsed. Archive may have changed; complete coverage not verified.')
 result={'items':out,'advertised':count};CACHE[key]=(time.time(),result);return result

def pib_range(start,end,progress=lambda x:None):
 a=date.fromisoformat(start);z=date.fromisoformat(end)
 if a>z or (z-a).days>62:raise ValueError('Select a valid range of up to 63 calendar days.')
 months=[];y,m=a.year,a.month
 while (y,m)<=(z.year,z.month):
  months.append((y,m));m+=1
  if m==13:y+=1;m=1
 allitems=[];checks=[]
 for y,m in months:
  progress(f'Loading English archive: {calendar.month_name[m]} {y}…')
  result=month_pib(y,m);allitems.extend(result['items']);checks.append({'month':f'{y}-{m:02d}','advertised':result['advertised'],'parsed':len(result['items'])})
 items=sorted([x for x in allitems if start<=x['date']<=end],key=lambda x:(x['date'],int(x['id'])),reverse=True)
 counts={}; d=a
 while d<=z:counts[d.isoformat()]=0;d+=timedelta(days=1)
 for x in items:counts[x['date']]+=1
 return {'source':'pib','start':start,'end':end,'items':items,'days':counts,'checks':checks,'complete':True,'coverage':'All releases listed by PIB Delhi, English, all ministries. Other regional offices are outside this scope.'}

def pdf_sections(blob,month,year,url):
 doc=pymupdf.open(stream=blob,filetype='pdf');items=[]
 for i,page in enumerate(doc):
  text=page.get_text().strip()
  if len(re.findall('[A-Za-z]',text))<60:continue
  if len(re.findall('[\u0900-\u097f]',text))>20:continue
  lines=[re.sub(r'\s+',' ',v).strip() for v in text.splitlines() if len(v.strip())>12]
  heading=' · '.join(lines[:2])[:180] or f'Page {i+1}'
  items.append({'id':f'{year}-{month:02d}-p{i+1}','title':f'Page {i+1} — {heading}','date':f'{year}-{month:02d}','link':url+f'#page={i+1}','text':text,'source':'yojana','page':i+1})
 if not items:raise ValueError('No English selectable text found. Scanned issues need OCR; this connector does not pretend to read them.')
 return {'source':'yojana','start':f'{year}-{month:02d}-01','end':f'{year}-{month:02d}-{calendar.monthrange(year,month)[1]}','items':items,'complete':len(items)==len(doc),'pdf_pages':len(doc),'text_pages':len(items),'issue':f'{calendar.month_name[month]} {year}','url':url,'coverage':f'English Yojana issue; {len(items)} pages with extractable English text out of {len(doc)} PDF pages. Page sections, not inferred article boundaries. No weekly issue exists.'}

def yojana_issue(month,year,progress=lambda x:None):
 key=('yojana',year,month)
 if key in CACHE:return CACHE[key][1]
 s=session();progress('Looking up the exact English Yojana issue in the official archive…')
 url=YARCH+str(year);r=s.get(url,timeout=75);r.raise_for_status();p=BeautifulSoup(r.content,'html.parser');links=[]
 mon=calendar.month_name[month]
 for a in p.select('a[href]'):
  link=urljoin(YBASE,a['href']);decoded=__import__('urllib.parse',fromlist=['unquote']).unquote(link)
  if '.pdf' in decoded.lower() and re.search(r'English',decoded,re.I) and str(year) in decoded and re.search(mon,decoded,re.I):links.append(link)
 # A missing issue is not substituted with another month or a third-party digest.
 if not links:raise ValueError(f'The official archive does not list an English Yojana PDF for {mon} {year}. No other month was substituted. Choose an available issue, or upload your English PDF below. Official archive: {url}')
 pdfurl=links[0];progress(f'Downloading English Yojana: {mon} {year}…');r=s.get(pdfurl,timeout=85);r.raise_for_status()
 if not r.content.startswith(b'%PDF'):raise ValueError('The issue link did not return a PDF.')
 result=pdf_sections(r.content,month,year,pdfurl);CACHE[key]=(time.time(),result);return result

def article(prid):
 if not re.fullmatch(r'\d{4,12}',prid):raise ValueError('Invalid PIB release ID.')
 url=f'https://www.pib.gov.in/PressReleasePage.aspx?PRID={prid}&reg=3&lang=1';r=session().get(url,timeout=75);r.raise_for_status();p=BeautifulSoup(r.content,'html.parser')
 body=p.select_one('#pibReleaseBody') or p.select_one('.innner-page-main-about-us-content-right-part') or p.select_one('.releasebody')
 if not body:raise ValueError('Official release body could not be identified; refusing to use navigation text.')
 for n in body.select('script,style,nav'):n.decompose()
 text=body.get_text('\n',strip=True)
 if not english(text):raise ValueError('Release is not English; it was not passed to generation.')
 return {'id':prid,'text':text,'link':url}

