"""Private, allowlisted request-failure diagnostics; never saves request bodies."""
import json
import re
import traceback
from datetime import datetime, timezone
from importlib.metadata import version, PackageNotFoundError
from urllib.parse import quote
from uuid import uuid4


class RequestFailure(str):
    """Keep the existing (None, error string) interface, with local retry metadata."""
    def __new__(cls, message, http_code=None):
        obj=super().__new__(cls,message);obj.http_code=http_code;return obj


def sanitize(value, secrets=(), payloads=()):
    text=str(value)
    for secret in (*secrets,*payloads):
        if isinstance(secret,str) and secret:
            for form in (secret,quote(secret,safe=''),json.dumps(secret,ensure_ascii=False)[1:-1],json.dumps(secret)[1:-1]):
                text=text.replace(form,'[REDACTED]')
    text=re.sub(r'(?i)https?://[^\s<>]+','[URL omitted]',text)
    text=re.sub(r'AIza[\w-]+','[REDACTED]',text)
    text=re.sub(r'(?i)\bBearer\s+[^\s,;\"\x27}]+','Bearer [REDACTED]',text)
    text=re.sub(r'(?i)([\"\x27]?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|x-goog-api-key|password|cookie|secret)[\"\x27]?\s*[:=]\s*)(?:[\"\x27][^\"\x27]*[\"\x27]|[^\s,;}]+)',r'\1[REDACTED]',text)
    text=re.sub(r'[A-Za-z0-9+/=_-]{128,}','[binary/long token omitted]',text)
    return text[:4000]


def capture(error, contents, *, output_dir, model, tools, system_prompt, api_key, stage):
    texts=[system_prompt];images=[];kinds=[]
    def field(obj,key):return obj.get(key) if isinstance(obj,dict) else getattr(obj,key,None)
    for part in contents:
        text=part if isinstance(part,str) else field(part,'text')
        if isinstance(text,str):texts.append(text);kinds.append('text')
        blob=field(part,'inline_data') if not isinstance(part,str) else None
        if blob is not None:
            data=field(blob,'data');images.append({'mime_type':field(blob,'mime_type'),'bytes':len(data) if isinstance(data,(bytes,str)) else None});kinds.append('inline_data')
    clean=lambda v:sanitize(v,(api_key,),texts)
    allowed={'error','code','status','message','details','@type','fieldViolations','field','description','reason','domain','retryDelay'}
    def structured(v,depth=0):
        if depth>8:return '[depth limit]'
        if isinstance(v,dict):return {k:structured(x,depth+1) for k,x in v.items() if k in allowed}
        if isinstance(v,list):return [structured(x,depth+1) for x in v[:30]]
        if v is None or isinstance(v,(bool,int,float)):return v
        return clean(v) if isinstance(v,str) else '[unsupported value omitted]'
    code=getattr(error,'code',None)
    if not isinstance(code,int):code=getattr(getattr(error,'response',None),'status_code',None)
    if not isinstance(code,int):code=None
    message=clean(getattr(error,'message',None) or str(error))
    status=clean(getattr(error,'status','') or '')
    try:sdk=version('google-genai')
    except PackageNotFoundError:sdk='unavailable'
    diagnostic=dict(schema_version=1,created_at=datetime.now(timezone.utc).isoformat(),stage=stage,
        exception_class=type(error).__module__+'.'+type(error).__name__,http_code=code,status=status,message=message,
        structured_error=structured(getattr(error,'details',None)),
        traceback=[{'file':clean(f.filename),'line':f.lineno,'function':f.name} for f in traceback.extract_tb(error.__traceback__)],
        request={'model':model,'tools':tools,'temperature':0.0,'system_instruction_present':bool(system_prompt),
                 'system_instruction_chars':len(system_prompt),'content_part_kinds':kinds,'text_chars':[len(t) for t in texts[1:]],'images':images},
        google_genai_version=sdk,redaction='allowlisted error fields; no headers, URLs, request text, image bytes, locals or source-code lines')
    try:
        with (output_dir/('retrieve_error_'+uuid4().hex+'.json')).open('x',encoding='utf-8') as handle:
            json.dump(diagnostic,handle,ensure_ascii=False,indent=2)
    except OSError:
        print('[Retrieve] Private diagnostic could not be saved')
    return RequestFailure(f'{code or "API_ERROR"} {status} {message}'.strip(),code)
