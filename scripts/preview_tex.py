#!/usr/bin/env python3
"""Preflight task/sheet drafts with the service renderer, without a database."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import UUID

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))


def sha(value):
    return hashlib.sha256(value).hexdigest()


def verify(expected):
    from core.tex_toolchain import build_contract
    contract=build_contract(ROOT,ROOT/'.local/tectonic-cache')
    supplied=ROOT/'toolchain-manifest.json'
    if supplied.exists():
        downloaded=json.loads(supplied.read_text())
        if downloaded['contract_id']!=contract['contract_id'] or downloaded['files']!=contract['files']:
            changed=sorted(name for name in set(downloaded['files'])|set(contract['files'])
                           if downloaded['files'].get(name)!=contract['files'].get(name))
            raise ValueError('Toolchain files differ from the downloaded manifest: '+', '.join(changed[:10])+'. Download a newly prepared archive; do not regenerate its manifest locally.')
    if expected and contract['contract_id']!=expected:
        raise ValueError('Toolchain differs from the current service contract; download it again')
    return contract


def draft_projects(data):
    from core.documents import project_for,TEMPLATE
    from core.content import image_list,normalize_blocks,numbering_start
    kind=data.get('kind','worksheet')
    rows=data.get('problems')
    if kind not in {'problem','worksheet'} or not isinstance(rows,list) or not 0<=len(rows)<=300 or (not rows and not data.get('blocks')):
        raise ValueError('kind: problem/worksheet; problems: 0–300 draft objects; text-only worksheets require blocks')
    if kind=='problem' and len(rows)!=1:raise ValueError('One task per problem preview')
    problems=[]
    for index,row in enumerate(rows,1):
        if not isinstance(row,dict):raise ValueError('Each draft problem must be an object')
        values={name:row.get(name,'') for name in ['title','description','statement','solution','statement_tex','solution_tex']}
        if any(not isinstance(value,str) for value in values.values()):raise ValueError('Text fields must be strings')
        for name in ['title','statement','solution','statement_tex','solution_tex']:values[name]=values[name].strip()
        if not (values['statement'].strip() or values['statement_tex'].strip()):raise ValueError('Missing statement')
        if not (values['solution'].strip() or values['solution_tex'].strip()):raise ValueError('Missing agreed solution')
        identity=str(UUID(row['id'])) if row.get('id') else f'draft-{index:03d}'
        problems.append(SimpleNamespace(pk=identity,attribution=row.get('attribution',{}),statement_images=image_list(row.get('statement_images',[])),solution_images=image_list(row.get('solution_images',[])),**values))
    header=data.get('worksheet',{})
    if not isinstance(header,dict):raise ValueError('worksheet must be an object')
    title=(problems[0].title or 'Задача - предпросмотр') if kind=='problem' else header.get('title','')
    description=problems[0].description if kind=='problem' else header.get('description','')
    if isinstance(title,str):title=title.strip()
    if not isinstance(title,str) or not title.strip() or not isinstance(description,str):raise ValueError('Set worksheet title and description')
    worksheet=SimpleNamespace(title=title,description=description,is_problem=kind=='problem',template_version=header.get('template_version',TEMPLATE),numbering_start=numbering_start(header.get('numbering_start',1)))
    if 'blocks' in data:
        blocks,ids=normalize_blocks(data['blocks']);worksheet._document_blocks=blocks
        lookup={str(problem.pk):problem for problem in problems}
        if set(ids)!=set(lookup):raise ValueError('Draft problems must match the task blocks')
        problems=[lookup[identity] for identity in ids]
    assets=data.get('assets',{})
    images=[image for problem in problems for field in ['statement_images','solution_images'] for image in getattr(problem,field)]
    images += [image for block in getattr(worksheet,'_document_blocks',[]) for image in block.get('images',[])]
    if not isinstance(assets,dict) or any(image['id'] not in assets for image in images):raise ValueError('Every image must be included in assets as {id: {base64: PNG}}')
    allowed=[problem.pk for problem in problems]
    return {name:project_for(worksheet,problems,allowed,solutions,assets=assets)
            for name,solutions in [('statement',False),('with-solutions',True)]}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--expected-contract',required=True)
    parser.add_argument('--input',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    # This program deliberately does not load the app settings, users or database.
    os.environ.pop('DJANGO_SETTINGS_MODULE',None)
    from django.conf import settings
    settings.configure(BASE_DIR=ROOT,LOCAL_DIR=ROOT/'.local',USE_I18N=False,SECRET_KEY='local-preview-only',
                       DEFAULT_CHARSET='utf-8',REST_FRAMEWORK={},DATABASES={})
    from core.documents import render_pdf,flatten
    from core.tex_project import write_project
    from core.tex_runtime import job_directory
    contract=verify(args.expected_contract)
    if args.prepare:
        subprocess.run([sys.executable,str(ROOT/'scripts/setup_tex.py'),'--offline'],check=True)
        verify(args.expected_contract)
        return
    if not args.input or not args.output:parser.error('--input and --output are required')
    if args.output.exists():raise ValueError('Choose a new output directory for every revision')
    binary=ROOT/'.local/tools/tectonic'
    version=subprocess.check_output([str(binary),'--version'],text=True).strip()
    if version.lower()!=('tectonic '+contract['compiler']['version']).lower():raise ValueError('Wrong compiler version')
    source=args.input.read_bytes()
    data=json.loads(source)
    if not isinstance(data,dict):raise ValueError('Draft must be an object')
    projects=draft_projects(data)
    payloads={};report={'toolchain_id':contract['contract_id'],'compiler':version,
        'input_sha256':sha(source),'template_version':contract['template_version'],
        'status':'requires_visual_review_and_user_confirmation','artifacts':{}}
    with job_directory(ROOT/'.local/tex-previews') as local:
        (local/'tectonic-cache').symlink_to((ROOT/'.local/tectonic-cache').resolve(),target_is_directory=True)
        settings.LOCAL_DIR=local;settings.TEX_COMPILER=str(binary)
        for name,project in projects.items():
            diagnostics={}
            payloads[name]=render_pdf(project,diagnostics=diagnostics,cache=False)
            report['artifacts'][name]={'pdf_sha256':sha(payloads[name]),
                'project_sha256':sha(json.dumps(project,sort_keys=True,ensure_ascii=False).encode()),
                'diagnostics':diagnostics}
    args.output.mkdir(parents=True,mode=0o700)
    for name,project in projects.items():
        (args.output/(name+'.pdf')).write_bytes(payloads[name])
        (args.output/(name+'.tex')).write_text(flatten(project))
        write_project(project,args.output/name)
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
