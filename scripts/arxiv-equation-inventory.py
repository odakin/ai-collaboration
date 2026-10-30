#!/usr/bin/env python3
"""Extract numbered rows and complete equation groups from arXiv HTML without MathML duplication, warn on numbering gaps and duplicate rows; --selftest.

The output is a transcription inventory, not a mathematical verification.
MathML alttext is preferred to rendered child nodes. Untagged preceding rows
are retained through equation_group, which may be shared by several numbers.
Uses only the Python standard library; does not download or execute HTML.

Collapse warnings (stderr, the output is still written): a subequation group
can come out as one entry, or one term can land in two rows. The script warns
when a numbering series skips (2.1 -> 2.3, 5a -> 5c, or a series not starting
at 1), when a number appears twice, and when two numbers carry the same row
text. Labels it cannot parse (roman numerals, starred tags) are not checked.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: object = None

    def text(self):
        if self.tag=='math' and 'alttext' in self.attrs:
            return '$'+self.attrs['alttext']+'$'
        return ' '.join(v.text() if isinstance(v,Node) else v.strip()
                        for v in self.children if isinstance(v,Node) or v.strip()).strip()


class Document(HTMLParser):
    VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root=Node('document')
        self.current=self.root
        self.nodes=[]

    def handle_starttag(self,tag,attrs):
        node=Node(tag,dict(attrs),parent=self.current)
        self.current.children.append(node)
        self.nodes.append(node)
        if tag not in self.VOID:
            self.current=node

    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self,tag):
        node=self.current
        while node is not self.root and node.tag!=tag:
            node=node.parent
        if node is not self.root:
            self.current=node.parent

    def handle_data(self,data):
        self.current.children.append(data)


def ancestor(node,predicate):
    while node is not None:
        if predicate(node):
            return node
        node=node.parent
    return None


def extract(html):
    document=Document()
    document.feed(html)
    entries=[]
    for node in document.nodes:
        if 'ltx_tag_equation' not in node.attrs.get('class','').split():
            continue
        row=ancestor(node,lambda x:x.tag=='tr') or node.parent
        own=ancestor(node,lambda x:bool(x.attrs.get('id')))
        group=ancestor(node,lambda x:x.tag=='table') or row
        entries.append(dict(id=own.attrs['id'] if own else None,number=node.text(),
                            numbered_row=row.text(),equation_group=group.text()))
    return entries


NUMBER=re.compile(r'^\(?\s*((?:[A-Z]+\.?)?(?:\d+\.)*)(\d+)([a-z]?)\s*\)?$')


def collapse_warnings(entries):
    """Numbering gaps, repeated numbers and repeated row text, in document order."""
    warnings=[];seen={};rows={};last={};letters={}
    for entry in entries:
        label=entry['number'].strip()
        if label in seen:
            warnings.append(f'number {label} appears twice (entries {seen[label]} and {entry["id"]})')
        seen.setdefault(label,entry['id'])
        row=entry['numbered_row'];cut=row.rfind(label)
        row=(row[:cut]+row[cut+len(label):] if cut>=0 and label else row).strip()
        if row and row in rows and rows[row]!=label:
            warnings.append(f'{rows[row]} and {label} have the same row text (a term may be duplicated)')
        rows.setdefault(row,label)
        match=NUMBER.match(label)
        if not match:
            continue
        prefix,value,letter=match.group(1) or '',int(match.group(2)),match.group(3)
        key=(prefix,value)
        if key not in letters:
            previous=last.get(prefix,0)
            if value!=previous+1 and value>previous:
                warnings.append(f'numbering skips from {prefix}{previous} to {label}' if previous
                                else f'series {prefix or "(top level)"} starts at {label}, not 1')
            last[prefix]=max(previous,value)
            letters[key]=''
        if letter:
            expected=chr(ord(letters[key])+1) if letters[key] else 'a'
            if letter!=expected and letter>letters[key]:
                warnings.append(f'subequation letters skip from {prefix}{value}{letters[key] or "(none)"} to {label}')
            letters[key]=max(letters[key],letter)
    return warnings


def selftest():
    fixture='''<table id="group" class="ltx_equationgroup">
    <tbody><tr><td><math alttext="f(x)="><mi>DO_NOT_DUPLICATE</mi></math></td></tr></tbody>
    <tbody id="eq-one"><tr><td><math alttext="x^2 &amp; y"/></td><td><span class="ltx_tag_equation">(I)</span></td></tr></tbody>
    <tbody id="eq-two"><tr><td>second</td><td><span class="ltx_tag ltx_tag_equation">(II)</span></td></tr></tbody></table>'''
    result=extract(fixture)
    assert len(result)==2
    assert result[0]['id']=='eq-one' and result[1]['id']=='eq-two'
    assert result[0]['number']=='(I)'
    assert '$f(x)=$' in result[0]['equation_group']
    assert '$f(x)=$' not in result[0]['numbered_row']
    assert result[0]['equation_group']==result[1]['equation_group']
    assert '$x^2 & y$' in result[0]['numbered_row']
    assert 'DO_NOT_DUPLICATE' not in json.dumps(result)
    assert extract('<p>no numbered equations</p>')==[]
    # Last-row-only extraction loses a required part of the fixture.
    assert result[0]['numbered_row']!=result[0]['equation_group']
    # Collapse warnings: roman labels are skipped; a clean series stays silent.
    assert collapse_warnings(result)==[]
    def rows(*pairs):
        return [dict(id=f'e{i}',number=n,numbered_row=f'{body} {n}',equation_group='') for i,(n,body) in enumerate(pairs)]
    clean=rows(('(1)','a'),('(2a)','b'),('(2b)','c'),('(3)','d'),('(A1)','e'),('(A2)','f'),('(2.1)','g'),('(2.2)','h'))
    assert collapse_warnings(clean)==[],f'collapse warnings: clean series warned {collapse_warnings(clean)}'
    broken=rows(('(1)','a'),('(3)','b'),('(4a)','c'),('(4c)','d'),('(5)','c'),('(5)','x'),('(2.2)','y'))
    found=collapse_warnings(broken)
    assert any('skips from 1 to (3)' in w for w in found),f'collapse warnings: {found}'
    assert any('letters skip from 4a to (4c)' in w for w in found),f'collapse warnings: {found}'
    assert any('(4a) and (5) have the same row text' in w for w in found),f'collapse warnings: {found}'
    assert any('(5) appears twice' in w for w in found),f'collapse warnings: {found}'
    assert any('series 2. starts at (2.2)' in w for w in found),f'collapse warnings: {found}'
    assert len(found)==5,f'collapse warnings: {found}'
    with tempfile.TemporaryDirectory() as temp:
        source=Path(temp)/'input.html';output=Path(temp)/'output.json'
        source.write_text(fixture,encoding='utf-8');output.write_text('sentinel')
        for flag,value in [('--expect-count','9'),('--sha256','bad-digest')]:
            process=subprocess.run([sys.executable,__file__,str(source),'--output',str(output),flag,value],capture_output=True,text=True)
            assert process.returncode!=0 and output.read_text()=='sentinel'
        process=subprocess.run([sys.executable,__file__,str(source),'--output',str(source)],capture_output=True,text=True)
        assert process.returncode!=0 and source.read_text()==fixture
        gapped=fixture.replace('(II)','(4)').replace('(I)','(2)')
        source.write_text(gapped,encoding='utf-8')
        process=subprocess.run([sys.executable,__file__,str(source),'--output',str(output)],capture_output=True,text=True)
        assert process.returncode==0 and 'WARNING' in process.stderr and 'skips from 2 to (4)' in process.stderr,f'collapse warnings (CLI): {process.stderr}'
        assert len(json.loads(output.read_text()))==2
    print('PASS: equation groups, alttext, labels, row-loss foil, collapse warnings and fail-before-write guards')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('html',nargs='?',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--expect-count',type=int)
    parser.add_argument('--selftest',action='store_true')
    args=parser.parse_args()
    if args.selftest:
        selftest();return
    if args.html is None or args.output is None:
        parser.error('html and --output are required')
    if args.html.resolve()==args.output.resolve():
        parser.error('output must differ from the source HTML')
    raw=args.html.read_bytes()
    if args.sha256 and sha256(raw).hexdigest()!=args.sha256:
        raise SystemExit('input SHA-256 mismatch; output not written')
    result=extract(raw.decode('utf-8'))
    if args.expect_count is not None and len(result)!=args.expect_count:
        raise SystemExit(f'expected {args.expect_count} equations, found {len(result)}; output not written')
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    warnings=collapse_warnings(result)
    for warning in warnings:
        print(f'WARNING: {warning}',file=sys.stderr)
    print(f'wrote {len(result)} equation records'+(f', {len(warnings)} collapse warning(s) on stderr' if warnings else ''))


if __name__=='__main__':
    main()
