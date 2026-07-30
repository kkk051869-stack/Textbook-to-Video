#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Check images, tables, and section breaks in moban.docx
"""
from docx import Document
from docx.shared import Pt, Emu
from docx.oxml.ns import qn, nsmap
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

doc = Document(r'D:\text python\Textbook-to-Video-master\Textbook-to-Video-master\docs\moban.docx')

# Check all paragraphs for images
print("=== 段落中的图片 ===")
for i, p in enumerate(doc.paragraphs):
    for r in p.runs:
        drawings = r._element.findall('.//' + qn('wp:docPr'))
        if drawings:
            text = p.text[:50] if p.text else '(空/图片)'
            print(f"  [{i}] 段落含图片, text='{text}'")
            for d in drawings:
                print(f"       docPr name={d.get('name')}")

# Check body-level drawings (inline images not in paragraphs)
print("\n=== Body 级别的图片/表格 ===")
body = doc.element.body
children = list(body)
for idx, child in enumerate(children):
    tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
    if tag in ('tbl', 'sectPr'):
        print(f"  子元素[{idx}]: {tag}")
        if tag == 'tbl':
            rows = child.findall('.//' + qn('w:tr'))
            print(f"    表格: {len(rows)} 行")
    # Check for drawings at body level
    drawings = child.findall('.//' + qn('wp:docPr'))
    if drawings and tag == 'p':
        pass  # already handled above

# Check for body-level drawings (anchor/absolute positioned images)
print("\n=== 查找锚定图片 (非内联) ===")
all_drawings = body.findall('.//' + qn('wp:docPr'))
print(f"  总共找到 {len(all_drawings)} 个图片元素")

# Check section properties in detail
print("\n=== 节的详细属性 ===")
for i, sec in enumerate(doc.sections):
    sectPr = sec._sectPr
    print(f"\n  节 {i}:")
    
    # Columns
    cols = sectPr.find(qn('w:cols'))
    if cols is not None:
        print(f"    分栏: {cols.attrib}")
    
    # Page size
    pgSz = sectPr.find(qn('w:pgSz'))
    if pgSz is not None:
        print(f"    页面大小: {pgSz.attrib}")
    
    # Margins
    pgMar = sectPr.find(qn('w:pgMar'))
    if pgMar is not None:
        print(f"    页边距: {pgMar.attrib}")
    
    # Columns space
    col = sectPr.find(qn('w:col'))
    if col is not None:
        print(f"    栏: {col.attrib}")

# Count tables
print(f"\n=== 表格数量: {len(doc.tables)} ===")
for idx, table in enumerate(doc.tables):
    print(f"  表格 {idx}: {len(table.rows)} 行 x {len(table.columns)} 列")
    # Check if first row has content
    if table.rows:
        first_cells = [c.text.strip()[:30] for c in table.rows[0].cells]
        print(f"    第一行: {first_cells}")
