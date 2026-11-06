import contextlib
import hashlib
import json
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_download as download


@contextlib.contextmanager
def server(payload, behavior='interrupt'):
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            index=len(calls);calls.append(dict(self.headers))
            start=int(self.headers.get('Range','bytes=0-')[6:].split('-')[0])
            ranged=bool(self.headers.get('Range'))
            self.send_response(206 if ranged else 200)
            self.send_header('ETag','"changed"' if behavior=='changed' and index==1 else '"fixture"')
            self.send_header('Content-Length',str(len(payload)-start))
            if ranged:self.send_header('Content-Range',f'bytes {start+(1 if behavior=="bad-range" else 0)}-{len(payload)-1}/{len(payload)}')
            self.end_headers()
            chunk=payload[start:]
            if index==0 and behavior in ('interrupt','changed','bad-range'):chunk=chunk[:70000]
            try:self.wfile.write(chunk);self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError):pass
            if len(chunk)!=len(payload)-start:
                self.connection.shutdown(socket.SHUT_RDWR);self.connection.close()
    http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
    try:yield 'http://127.0.0.1:'+str(http.server_port)+'/fixture',calls
    finally:http.shutdown();http.server_close();worker.join()


class DownloadTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.target=Path(temp.name)/'archive.zip'
        self.payload=bytes(range(256))*2048
        self.digest=hashlib.sha256(self.payload).hexdigest()

    def fetch(self,url,**kw):
        return download.fetch(url,self.target,self.digest,allow_local_http=True,retry_delay=0,**kw)

    def test_interrupted_download_resumes_across_invocations_and_reports_actual_bytes(self):
        with server(self.payload) as (url,calls):
            with self.assertRaises(RuntimeError):self.fetch(url,retries=1)
            size=self.target.with_name('archive.zip.part').stat().st_size
            self.assertGreater(size,0);self.assertLess(size,len(self.payload));self.assertFalse(self.target.exists())
            reports=[];self.fetch(url,progress=lambda n,total:reports.append((n,total)))
            self.assertEqual(calls[1]['Range'],f'bytes={size}-')
            self.assertEqual(calls[1]['If-Range'],'"fixture"')
            self.assertEqual(reports[-1],(len(self.payload),len(self.payload)))
            self.assertEqual(self.target.read_bytes(),self.payload)
            self.fetch(url);self.assertEqual(len(calls),2)

    def test_changed_etag_restarts_instead_of_appending_other_entity(self):
        with server(self.payload,'changed') as (url,calls):
            self.fetch(url)
            self.assertIn('Range',calls[1]);self.assertNotIn('Range',calls[2])
            self.assertEqual(self.target.read_bytes(),self.payload)

    def test_bad_range_never_publishes_partial_file(self):
        with server(self.payload,'bad-range') as (url,calls):
            with self.assertRaises(RuntimeError):self.fetch(url,retries=2)
            self.assertFalse(self.target.exists())

    def test_exact_url_is_required_to_reuse_partial(self):
        with server(self.payload) as (url,calls):
            with self.assertRaises(RuntimeError):self.fetch(url,retries=1)
            self.fetch(url+'?different=1')
            self.assertNotIn('Range',calls[1])

    def test_wrong_digest_keeps_old_destination_and_rejects_payload(self):
        self.target.write_bytes(b'old verified version')
        with server(self.payload,'complete') as (url,calls):
            with self.assertRaises(RuntimeError):download.fetch(url,self.target,'0'*64,allow_local_http=True,retries=1)
        self.assertEqual(self.target.read_bytes(),b'old verified version')

    def test_size_limit_and_insecure_host_rejected(self):
        with server(self.payload,'complete') as (url,calls):
            with self.assertRaises(RuntimeError):self.fetch(url,max_bytes=100,retries=1)
            self.assertFalse(self.target.exists())
        for url in ('http://example.test/file','https://user:secret@example.test/file','file:///tmp/file'):
            with self.assertRaises(ValueError):download.fetch(url,self.target,self.digest)

    def test_completed_partial_is_verified_and_committed_without_network(self):
        url='https://example.test/fixture.zip'
        self.target.with_name('archive.zip.part').write_bytes(self.payload)
        self.target.with_name('archive.zip.part.json').write_text(json.dumps({'url':url,'sha256':self.digest}))
        with patch.object(download.urllib.request,'urlopen') as request:
            download.fetch(url,self.target,self.digest)
        request.assert_not_called();self.assertEqual(self.target.read_bytes(),self.payload)

    def test_symlink_partial_is_not_followed(self):
        outside=self.target.parent/'outside';outside.write_bytes(b'keep')
        self.target.with_name('archive.zip.part').symlink_to(outside)
        with self.assertRaises(ValueError):download.fetch('https://example.test/file',self.target,self.digest)
        self.assertEqual(outside.read_bytes(),b'keep')

if __name__=='__main__':unittest.main()
