"""Explicit small public-fixture download. No application settings or user data are read."""
import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path


def checked_download(url, target, expected):
    data=urllib.request.urlopen(url,timeout=60).read()
    if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('fixture checksum mismatch')
    target.write_bytes(data)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True,type=Path);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    fixture=json.loads(Path(__file__).with_name('fixtures.json').read_text())
    for key,name in [('face','face.png'),('model','face.task')]:checked_download(fixture[key]['url'],args.out/name,fixture[key]['sha256'])
    voice=fixture['voice'];url='https://datasets-server.huggingface.co/rows?'+urllib.parse.urlencode(dict(dataset=voice['dataset'],config='default',split='test',offset=0,length=2))
    rows=json.load(urllib.request.urlopen(url,timeout=60))['rows']
    refs=[]
    for index,row in enumerate(rows):
        src=row['row']['audio'][0]['src']
        if '/--/'+voice['revision']+'/--/' not in src:raise ValueError('dataset revision mismatch')
        checked_download(src,args.out/f'voice-{index}.flac',voice['sha256'][index])
        refs.append(row['row']['text'])
    # Public reference text stays in the explicit local fixture directory, never in aggregate artifacts.
    (args.out/'references.json').write_text(json.dumps(refs,ensure_ascii=False))
    (args.out/'provenance.json').write_text(json.dumps(fixture,indent=2))


if __name__=='__main__':main()
