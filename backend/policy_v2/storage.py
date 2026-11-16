"""Content-addressed immutable bytes. DB references are committed only after put succeeds."""
import hashlib
import os
import tempfile
from pathlib import Path

class LocalStore:
    def __init__(self, root): self.root=Path(root)
    def put(self, data, mime):
        sha=hashlib.sha256(data).hexdigest(); key=f'raw/{sha[:2]}/{sha}'
        dest=self.root/key; dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            if hashlib.sha256(dest.read_bytes()).hexdigest()!=sha: raise ValueError('stored_object_corrupt')
        else:
            fd,name=tempfile.mkstemp(dir=dest.parent)
            try:
                with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
                os.replace(name,dest)
            finally:
                if os.path.exists(name): os.unlink(name)
        return {'sha':sha,'key':key,'size':len(data),'mime':mime[:150]}
    def read(self,key):
        p=(self.root/key).resolve()
        if not p.is_relative_to(self.root.resolve()): raise ValueError('invalid_object_key')
        return p.read_bytes()

class COSStore:
    def __init__(self, settings):
        from qcloud_cos import CosConfig, CosS3Client
        if not all([settings.cos_region,settings.cos_bucket,settings.cos_secret_id,settings.cos_secret_key]): raise ValueError('COS configuration incomplete')
        self.bucket=settings.cos_bucket
        self.client=CosS3Client(CosConfig(Region=settings.cos_region,SecretId=settings.cos_secret_id,SecretKey=settings.cos_secret_key,Scheme='https'))
    def put(self,data,mime):
        sha=hashlib.sha256(data).hexdigest();key=f'raw/{sha[:2]}/{sha}'
        self.client.put_object(Bucket=self.bucket,Key=key,Body=data,ContentType=mime,EnableMD5=True,ServerSideEncryption='AES256',Metadata={'sha256':sha})
        # Verify actual bytes; avoid assuming multipart ETag is a SHA or trusting metadata alone.
        if hashlib.sha256(self.read(key)).hexdigest()!=sha: raise ValueError('object_verification_failed')
        return {'sha':sha,'key':key,'size':len(data),'mime':mime[:150]}
    def read(self,key):
        return self.client.get_object(Bucket=self.bucket,Key=key)['Body'].get_raw_stream().read()

def make_store(settings):
    if settings.storage_backend=='local': return LocalStore(settings.object_root)
    if settings.storage_backend=='cos': return COSStore(settings)
    raise ValueError('unknown_storage_backend')
