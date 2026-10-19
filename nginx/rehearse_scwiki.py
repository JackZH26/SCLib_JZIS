"""Owned loopback transport and local-preview rehearsal; never writes to VPS."""
import argparse,collections,concurrent.futures,hashlib,http.client,json,math,pathlib,socket,subprocess,tempfile,threading,time,urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

ROOT=pathlib.Path(__file__).resolve().parents[1]
FILES=['scwiki-http.conf','scwiki-proxy-common.conf','scwiki-server.conf']

def require(condition,message):
    if not condition:raise AssertionError(message)

def request(port,path,method='GET',headers=None,host='127.0.0.1'):
    c=http.client.HTTPConnection(host,port,timeout=5)
    try:
        c.request(method,path,headers=headers or {});r=c.getresponse()
        return r.status,r.read(),{k.lower():v for k,v in r.getheaders()}
    finally:c.close()

class Stub(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def reply(self,status,body=b'',headers=None):
        self.send_response(status)
        self.send_header('Content-Length',str(len(body)))
        for key,value in (headers or {}).items():self.send_header(key,value)
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(body)
    def respond(self):
        if self.path=='/api/scwiki/v1/upstream-429':
            self.reply(429,b'upstream-limited',{'Retry-After':'17'});return
        if self.command not in ['GET','HEAD','OPTIONS']:
            self.reply(405,headers={'Allow':'GET, HEAD, OPTIONS'});return
        if self.command=='OPTIONS':
            self.reply(204,headers={'Allow':'GET, HEAD, OPTIONS'});return
        self.reply(200,json.dumps({'path':self.path,'headers':dict(self.headers)}).encode(),{'Content-Type':'application/json','ETag':'"fixture-v1"'})
    do_GET=respond;do_HEAD=respond;do_OPTIONS=respond;do_POST=respond

def owned_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    require(port>1024 and port not in [3100,3107,8000],'Unsafe rehearsal port')
    # Both families are needed to demonstrate distinct connection-peer buckets.
    with socket.socket(socket.AF_INET6) as s:s.bind(('::1',port))
    return port

@contextmanager
def proxy(exe,upstream,report):
    require(1024<upstream<65536,'Unsafe upstream')
    with tempfile.TemporaryDirectory(prefix='scwiki-proxy-') as tmp:
        folder=pathlib.Path(tmp);port=owned_port()
        common=(ROOT/'nginx/scwiki-proxy-common.conf').read_text()
        require(common.count('http://127.0.0.1:3100;')==1,'Upstream template drift')
        (folder/'common.conf').write_text(common.replace('http://127.0.0.1:3100;',f'http://127.0.0.1:{upstream};'))
        server=(ROOT/'nginx/scwiki-server.conf').read_text()
        require(server.count('/etc/nginx/snippets/scwiki-proxy-common.conf')==2,'Include template drift')
        server=server.replace('/etc/nginx/snippets/scwiki-proxy-common.conf',str(folder/'common.conf'))
        conf=f'''daemon off; master_process off; worker_processes 1;
pid {folder}/nginx.pid; error_log {folder}/error.log warn;
events {{ worker_connections 128; }}
http {{ access_log off; server_tokens off;
 client_body_temp_path {folder}/body; proxy_temp_path {folder}/proxy;
 {(ROOT/'nginx/scwiki-http.conf').read_text()}
 server {{ listen 127.0.0.1:{port}; listen [::1]:{port}; server_name localhost;
 {server}
 location / {{ proxy_pass http://127.0.0.1:{upstream}; }}
 }}
}}
'''
        config=folder/'nginx.conf';config.write_text(conf)
        cmd=[str(exe),'-p',str(folder)+'/', '-c',str(config)]
        subprocess.run(cmd+['-t'],capture_output=True,text=True,check=True)
        with (folder/'process.log').open('w') as log:
            process=subprocess.Popen(cmd,stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+5
                while True:
                    require(process.poll() is None,'Owned proxy exited before ready')
                    try:
                        with socket.create_connection(('127.0.0.1',port),timeout=.1):break
                    except OSError:
                        require(time.monotonic()<deadline,'Owned proxy readiness timeout');time.sleep(.03)
                yield port
            finally:
                if process.poll() is None:process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                report.setdefault('ownedProcessCleanup',[]).append({'pid':process.pid,'exitCode':process.returncode,'terminated':process.poll() is not None})
                report.setdefault('proxyErrorTails',[]).append((folder/'error.log').read_text()[:18000] if(folder/'error.log').exists()else'')

def run(exe,report):
    class Upstream(ThreadingHTTPServer):request_queue_size=64
    stub=Upstream(('127.0.0.1',0),Stub);thread=threading.Thread(target=stub.serve_forever,daemon=True);thread.start()
    try:
        with proxy(exe,stub.server_port,report) as port:
            spoof={'X-Forwarded-For':'203.0.113.17','X-Real-IP':'203.0.113.18','Forwarded':'for=203.0.113.19','CF-Connecting-IP':'203.0.113.20','True-Client-IP':'203.0.113.21'}
            status,body,_=request(port,'/api/scwiki/v1/search',headers=spoof);require(status==200,'Initial request failed')
            observed={k.lower():v for k,v in json.loads(body)['headers'].items()}
            require(observed.get('x-forwarded-for')==observed.get('x-real-ip')=='127.0.0.1','Spoofed forwarded identity reached upstream')
            require(not any(k in observed for k in ['forwarded','cf-connecting-ip','true-client-ip']),'Untrusted alternate identity retained')
            require(request(port,'/api/scwiki/v1/upstream-429')[2].get('retry-after')=='17','Upstream rate response replaced')
            require(request(port,'/api/scwiki/v1','HEAD')[1]==b'','HEAD body present')
            require(request(port,'/api/scwiki/v1','OPTIONS')[0]==204,'OPTIONS altered')
            require(request(port,'/api/scwiki/v1','POST')[0]==405,'Write method response altered')
            start=time.monotonic()
            def burst(i):
                paths=['/api/scwiki/v1','/api/scwiki/v1/search','/api/scwiki/v1/articles/x']
                h={**spoof,'X-Forwarded-For':'198.51.100.'+str(i+1)}
                return request(port,paths[i%3],headers=h)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:responses=list(pool.map(burst,range(64)))
            elapsed=time.monotonic()-start;accepted=sum(x[0]==200 for x in responses);limited=[x for x in responses if x[0]==429]
            report['burstDiagnostics']={'statuses':dict(collections.Counter(x[0]for x in responses)),'seconds':elapsed,'unexpected':[{'status':x[0],'body':x[1].decode(errors='replace')[:400]}for x in responses if x[0]not in [200,429]][:3]}
            require(limited and all(x[0] in [200,429]for x in responses),'No attributable rate enforcement')
            require(accepted<=21+math.ceil(elapsed*10)+2,'Changing forwarded headers escaped peer bucket')
            for _,body,headers in limited:
                require(headers.get('retry-after')=='3' and headers.get('cache-control')=='no-store','Missing retry/cache contract')
                require(headers.get('content-type','').startswith('application/json') and headers.get('x-content-type-options')=='nosniff','Unsafe edge error representation')
                require(json.loads(body)['code']=='RATE_LIMITED','Non-machine-readable edge rejection')
            status,body,_=request(port,'/api/scwiki/v1',host='::1');require(status==200,'Distinct IPv6 peer incorrectly exhausted')
            require(json.loads(body)['headers'].get('X-Real-IP')=='::1','IPv6 peer identity lost')
            for path in ['/scwiki','/api/unrelated','/api/scwiki/v10','/api/scwiki/v1suffix']:
                require(request(port,path)[0]==200,'Ordinary/prefix-neighbor route affected: '+path)
            # Wait only for the bounded limiter interval being tested, not a scheduler cycle.
            time.sleep(3.05);require(request(port,'/api/scwiki/v1')[0]==200,'No recovery after advertised Retry-After')
            report['transport']={'spoofedHeadersSanitized':True,'burstRequests':64,'accepted':accepted,'rejected':len(limited),'burstSeconds':elapsed,'distinctIPv6PeerPassed':True,'ordinaryAndPrefixNeighborRoutesUnaffected':True,'retryAfterRecoveryPassed':True,'upstream429Preserved':True,'HEADOPTIONSAnd405Preserved':True}
    finally:stub.shutdown();stub.server_close();thread.join(timeout=5)
    with urllib.request.urlopen('http://127.0.0.1:3107/api/scwiki/v1',timeout=5)as r:expected=json.load(r)['revision']
    with proxy(exe,3107,report) as port:
        status,body,headers=request(port,'/api/scwiki/v1/articles/scwiki-b1');require(status==200,'Real preview article failed through proxy')
        article=json.loads(body);require(article['revision']==expected,'Wrong real preview revision')
        tag=headers['etag'];require(request(port,'/api/scwiki/v1/articles/scwiki-b1',headers={'If-None-Match':tag})[:2]==(304,b''),'Conditional request altered')
        require(request(port,'/api/scwiki/v1/articles/scwiki-b1','HEAD')[1]==b'','Real HEAD body changed')
        require(request(port,'/api/scwiki/v1/topics','OPTIONS')[0]==204,'Real OPTIONS changed')
        status,body,headers=request(port,'/api/scwiki/v1/topics','POST');require(status==405 and json.loads(body)['code']=='METHOD_NOT_ALLOWED','Real read-only error changed')
        require(request(port,'/scwiki')[0]==200,'Real homepage unavailable')
        report['localPreviewIntegration']={'catalogueRevision':expected,'article':article['article']['id'],'GETConditionalHEADOPTIONS405AndHomepage':True}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--nginx',type=pathlib.Path,required=True);parser.add_argument('--output',type=pathlib.Path,required=True);args=parser.parse_args()
    report={'startedAt':time.time(),'passed':False,'productionChanged':False,'productionVerified':False,'harnessSha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),'sourceHashes':{f:hashlib.sha256((ROOT/'nginx'/f).read_bytes()).hexdigest()for f in FILES},'nginxBinarySha256':hashlib.sha256(args.nginx.read_bytes()).hexdigest()}
    if args.output.exists():
        previous=json.loads(args.output.read_text());archive=args.output.with_name(args.output.stem+'-history-'+str(previous['startedAt'])+'.json')
        require(not archive.exists(),'Previous rehearsal archive already exists')
        archive.write_text(args.output.read_text())
    def save():
        temp=args.output.with_suffix('.tmp');temp.write_text(json.dumps(report,indent=2)+'\n');temp.replace(args.output)
    save()
    try:run(args.nginx,report);report['passed']=True
    except Exception as exc:report['error']=repr(exc);raise
    finally:report['finishedAt']=time.time();save()
    print(json.dumps({k:v for k,v in report.items()if k!='proxyErrorTails'},indent=2))

if __name__=='__main__':main()
