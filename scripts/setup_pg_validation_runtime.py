#!/usr/bin/env python3
"""Build pinned real PostgreSQL/PostgREST in /tmp, without sudo/system installation.

Needs gcc/make/zlib headers, tar/dpkg-deb, HTTPS access. Runs at most two compiler
jobs. Sources/checksums come from upstream PostgreSQL, PostgREST GitHub and Ubuntu.
The OpenSSL package is extracted locally solely for headers/linker stubs.
"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request

PG_VERSION = '16.15'
REST_VERSION = '16.5'
PG_HASH = 'c1575341fa7bd40f5274ea465b34390f4dc64cdd0770af327005caaeb9f6b7ed'
REST_HASH = '5099e7ada38f9f6846cd87c14c5f158b7c165f1e9959665ad412e61f4dceba95'
SSL_SHA512 = 'e24c4b41e21fd6aafd1a27207e4840faea6ede4c08be14da5b36d32cb7eebb3aee0949da78c1b9b70b34fe850bd97a889a450b8c02d2529de182b355f853389e'
SSL_NAME = 'libssl-dev_3.0.13-0ubuntu3.16_amd64.deb'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', default='/tmp/jobseeker-pg-validation-runtime')
    args = parser.parse_args()
    runtime = Path(args.runtime).resolve()
    if not runtime.is_relative_to('/tmp') or runtime == Path('/tmp'):
        parser.error('runtime must be a dedicated child directory of /tmp')
    runtime.mkdir(parents=True, exist_ok=True)
    runtime_lock = (runtime / ".runtime.lock").open("a")
    fcntl.flock(runtime_lock, fcntl.LOCK_EX)
    downloads = runtime / 'downloads'
    downloads.mkdir(parents=True, exist_ok=True)

    def download(url, name, digest, algorithm='sha256'):
        path = downloads / name
        if not path.exists():
            with urllib.request.urlopen(url, timeout=60) as source, path.open('wb') as target:
                shutil.copyfileobj(source, target)
        if hashlib.new(algorithm, path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Checksum mismatch: '+name)
        print(name+': official checksum OK', flush=True)
        return path

    pg_name = f'postgresql-{PG_VERSION}.tar.bz2'
    pg_url = f'https://ftp.postgresql.org/pub/source/v{PG_VERSION}/{pg_name}'
    pg = download(pg_url, pg_name, PG_HASH)
    rest_name = f'postgrest-v{REST_VERSION}-linux-static-x86-64.tar.xz'
    rest_url = f'https://github.com/PostgREST/postgrest/releases/download/v{REST_VERSION}/{rest_name}'
    rest = download(rest_url, rest_name, REST_HASH)
    ssl = download('https://archive.ubuntu.com/ubuntu/pool/main/o/openssl/'+SSL_NAME, 'libssl-dev.deb', SSL_SHA512, 'sha512')
    # Reconfirm release metadata rather than trusting a similarly named third-party asset.
    with urllib.request.urlopen(f'https://api.github.com/repos/PostgREST/postgrest/releases/tags/v{REST_VERSION}', timeout=30) as response:
        metadata = json.load(response)
    asset = next(a for a in metadata['assets'] if a['name'] == rest_name)
    assert asset['browser_download_url'] == rest_url and asset['digest'] == 'sha256:'+REST_HASH
    manifest = {'postgresql': {'version': PG_VERSION, 'url': pg_url, 'sha256': PG_HASH},
                'postgrest': {'version': REST_VERSION, 'url': rest_url, 'sha256': REST_HASH},
                'openssl_headers': {'package': SSL_NAME, 'sha512': SSL_SHA512}}
    (runtime/'provenance.json').write_text(json.dumps(manifest, indent=2)+'\n')

    def run(*cmd, cwd=None, env=None, log='setup.log'):
        with (runtime/log).open('a') as output:
            subprocess.run(cmd, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT, check=True)

    headers = runtime/'openssl-dev'
    headers.mkdir(exist_ok=True)
    run('dpkg-deb','--extract',str(ssl),str(headers))
    for library in ['libssl','libcrypto']:
        link=headers/'usr/lib/x86_64-linux-gnu'/f'{library}.so.3'
        if not link.exists():
            link.symlink_to(f'/usr/lib/x86_64-linux-gnu/{library}.so.3')
    rest_dir=runtime/'postgrest'; rest_dir.mkdir(exist_ok=True)
    run('tar','-xf',str(rest),'-C',str(rest_dir))
    source=runtime/f'postgresql-{PG_VERSION}'
    if not source.exists():
        run('tar','-xf',str(pg),'-C',str(runtime))
    import os
    env={**os.environ,'CPPFLAGS':f'-I{headers}/usr/include -I{headers}/usr/include/x86_64-linux-gnu',
         'LDFLAGS':f'-L{headers}/usr/lib/x86_64-linux-gnu'}
    run('./configure',f'--prefix={runtime}/pgsql','--without-icu','--without-readline','--with-openssl',cwd=source,env=env,log='configure.log')
    run('make','-j2',cwd=source,log='build.log')
    run('make','install',cwd=source,log='install.log')
    run('make','-C','contrib/pgcrypto','install',cwd=source,log='install.log')
    for binary in [runtime/'pgsql/bin/postgres',rest_dir/'postgrest']:
        subprocess.run([str(binary),'--version'],check=True)
    print('Runtime ready. PostgreSQL has not been started; integration tests create their own disposable cluster.')


if __name__=='__main__':
    main()
