#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
List all styles used in both documents and convert formats
"""
from docx import Document
from docx.shared import Pt
from docx.enum.style import WD_STYLE_TYPE
import sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

moban_path = r'D:\text python\Textbook-to-Video-master\Textbook-to-Video-master\docs\moban.docx'
v6_path = r'D:\text python\Textbook-to-Video-master\Textbook-to-Video-master\docs\v6.docx'
output_path = r'D:\text python\Textbook-to-Video-master\Textbook-to-Video-master\docs\v6_formatted_v2.docx'

moban = Document(moban_path)
v6 = Document(v6_path)

# 找出所有在 moban 中使用但 v6 中没有使用的样式
moban_used = set(p.style.name for p in moban.paragraphs if p.style)
v6_used = set(p.style.name for p in v6.paragraphs if p.style)

all_styles = moban_used | v6_used

print("=== 所有样式 ===")
for sn in sorted(all_styles):
    in_moban = sn in moban_used
    in_v6 = sn in v6_used
    print(f"{sn}: moban={in_moban}, v6={in_v6}")

# 需要转换的样式: 所有moban中使用的样式
styles_to_convert = moban_used

print("\n=== 需要转换的样式 ===")
for sn in sorted(styles_to_convert):
    ms = moban.styles[sn]
    print(f"{sn}: font_size={Pt(ms.font.size).pt if ms.font.size else 'None'} line_spacing={ms.paragraph_format.line_spacing} align={ms.paragraph_format.alignment}")

# 执行转换
print("\n=== 执行转换 ===")
for sn in styles_to_convert:
    ms = moban.styles[sn]
    
    # v6 中没有该样式，需要创建
    if sn not in v6.styles:
        print(f"创建新样式: {sn}")
        new_style = v6.styles.add_style(sn, WD_STYLE_TYPE.PARAGRAPH)
        ns = new_style
    else:
        ns = v6.styles[sn]
    
    # 复制格式
    if ms.font.name:
        ns.font.name = ms.font.name
    if ms.font.size:
        ns.font.size = ms.font.size
    if ms.font.bold is not None:
        ns.font.bold = ms.font.bold
    if ms.font.italic is not None:
        ns.font.italic = ms.font.italic
    
    if ms.paragraph_format.space_before is not None:
        ns.paragraph_format.space_before = ms.paragraph_format.space_before
    if ms.paragraph_format.space_after is not None:
        ns.paragraph_format.space_after = ms.paragraph_format.space_after
    if ms.paragraph_format.line_spacing is not None:
        ns.paragraph_format.line_spacing = ms.paragraph_format.line_spacing
    if ms.paragraph_format.alignment is not None:
        ns.paragraph_format.alignment = ms.paragraph_format.alignment
    if ms.paragraph_format.first_line_indent is not None:
        ns.paragraph_format.first_line_indent = ms.paragraph_format.first_line_indent

# 保存
v6.save(output_path)
print(f"转换完成，已保存到: {output_path}")

# 验证
result = Document(output_path)
print(f"\n=== 验证结果 ===")
print(f"段落数: {len(result.paragraphs)}")

print("\n验证样式属性:")
for sn in sorted(styles_to_convert):
    s = result.styles[sn]
    print(f"{sn}: font_size={Pt(s.font.size).pt if s.font.size else 'None'} line_spacing={s.paragraph_format.line_spacing} align={s.paragraph_format.alignment}")
