"""
Apply formatting from a template document (moban.docx) to the content of a target document (v6.docx).
Uses python-docx to extract styles from the template and apply them to the target's content.
"""

from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
import os


def extract_style_info(template_doc):
    """Extract style properties from the template document."""
    style_map = {}
    for style in template_doc.styles:
        props = {}
        if style.font.name:
            props['font_name'] = style.font.name
        if style.font.name_east_asian:
            props['font_name_east_asian'] = style.font.name_east_asian
        if style.font.size:
            props['font_size'] = style.font.size
        if style.font.bold is not None:
            props['font_bold'] = style.font.bold
        if style.font.italic is not None:
            props['font_italic'] = style.font.italic
        if style.font.underline is not None:
            props['font_underline'] = style.font.underline
        if style.font.color and style.font.color.rgb:
            props['font_color'] = style.font.color.rgb
        if style.font.highlight_color is not None:
            props['font_highlight'] = style.font.highlight_color
        if style.paragraph:
            if style.paragraph.alignment is not None:
                props['alignment'] = style.paragraph.alignment
            if style.paragraph.space_before is not None and style.paragraph.space_before != Pt(0):
                props['space_before'] = style.paragraph.space_before
            if style.paragraph.space_after is not None and style.paragraph.space_after != Pt(0):
                props['space_after'] = style.paragraph.space_after
            if style.paragraph.line_spacing is not None:
                props['line_spacing'] = style.paragraph.line_spacing
            if style.paragraph.first_line_indent is not None:
                props['first_line_indent'] = style.paragraph.first_line_indent
            if style.paragraph.left_indent is not None:
                props['left_indent'] = style.paragraph.left_indent
            if style.paragraph.right_indent is not None:
                props['right_indent'] = style.paragraph.right_indent
            if style.paragraph.keep_together is not None:
                props['keep_together'] = style.paragraph.keep_together
            if style.paragraph.keep_with_next is not None:
                props['keep_with_next'] = style.paragraph.keep_with_next

        # Page breaks and widow/orphan control
        if style.paragraph:
            if style.paragraph.page_break_before is not None:
                props['page_break_before'] = style.paragraph.page_break_before
            if style.paragraph.widow_control is not None:
                props['widow_control'] = style.paragraph.widow_control

        if props:
            style_map[style.name] = props

    return style_map


def find_matching_style(target_style_name, template_style_map):
    """Find the best matching style in the template."""
    if not target_style_name:
        return 'Normal'

    # Direct match
    if target_style_name in template_style_map:
        return target_style_name

    # Try to match by common style categories
    style_aliases = {
        'Normal': ['Normal', 'Standard', 'Default'],
        'Heading 1': ['Heading 1', 'Title', 'Title 1'],
        'Heading 2': ['Heading 2', 'Subtitle', 'Subtitle 1'],
        'Heading 3': ['Heading 3'],
        'Heading 4': ['Heading 4'],
        'Heading 5': ['Heading 5'],
        'Heading 6': ['Heading 6'],
        'Heading 7': ['Heading 7'],
        'Heading 8': ['Heading 8'],
        'Heading 9': ['Heading 9'],
        'List Paragraph': ['List Paragraph', 'List'],
        'List Bullet': ['List Bullet', 'Bullet List'],
        'List Number': ['List Number', 'Numbered List'],
        'Title': ['Title', 'Cover Page'],
        'Subtitle': ['Subtitle', 'Section Heading'],
        'Quote': ['Quote', 'Block Quote'],
        'Intense Quote': ['Intense Quote', 'Block Quotation'],
        'Strong': ['Strong', 'Bold'],
        'Emphasis': ['Emphasis', 'Italic'],
    }

    target_canonical = None
    for canonical, aliases in style_aliases.items():
        if target_style_name in aliases:
            target_canonical = canonical
            break

    if target_canonical and target_canonical in template_style_map:
        return target_canonical

    # Fuzzy match by prefix
    base_name = target_style_name.split(' Char')[0].split(' ')[0]
    if base_name in template_style_map:
        return base_name

    # Check for Chinese style name patterns
    template_chinese_styles = {k: v for k, v in template_style_map.items()
                               if any(ord(c) > 127 for c in k)}
    target_is_chinese = any(ord(c) > 127 for c in target_style_name)

    if target_is_chinese:
        for t_name in template_chinese_styles:
            if t_name == target_style_name:
                return t_name

    return None


def copy_paragraph_formatting(src_para, dst_para, template_style_map):
    """Copy formatting properties from source to destination paragraph."""
    # Copy alignment
    if src_para.alignment is not None:
        dst_para.alignment = src_para.alignment

    # Copy spacing
    if src_para.paragraph_format.space_before:
        dst_para.paragraph_format.space_before = src_para.paragraph_format.space_before or src_para.paragraph_format.space_before
    if src_para.paragraph_format.space_after:
        dst_para.paragraph_format.space_after = src_para.paragraph_format.space_after or src_para.paragraph_format.space_after
    if src_para.paragraph_format.line_spacing:
        dst_para.paragraph_format.line_spacing = src_para.paragraph_format.line_spacing
    if src_para.paragraph_format.first_line_indent:
        dst_para.paragraph_format.first_line_indent = src_para.paragraph_format.first_line_indent
    if src_para.paragraph_format.left_indent:
        dst_para.paragraph_format.left_indent = src_para.paragraph_format.left_indent
    if src_para.paragraph_format.right_indent:
        dst_para.paragraph_format.right_indent = src_para.paragraph_format.right_indent

    # Copy keep_together, keep_with_next
    if src_para.paragraph_format.keep_together:
        dst_para.paragraph_format.keep_together = src_para.paragraph_format.keep_together
    if src_para.paragraph_format.keep_with_next:
        dst_para.paragraph_format.keep_with_next = src_para.paragraph_format.keep_with_next
    if src_para.paragraph_format.page_break_before:
        dst_para.paragraph_format.page_break_before = src_para.paragraph_format.page_break_before
    if src_para.paragraph_format.widow_control:
        dst_para.paragraph_format.widow_control = src_para.paragraph_format.widow_control

    # Copy run formatting
    for i, run in enumerate(dst_para.runs):
        if src_para.runs:
            src_run = src_para.runs[i] if i < len(src_para.runs) else src_para.runs[-1]
            if src_run.font.name:
                run.font.name = src_run.font.name
            if src_run.font.name_east_asian:
                run.font.name_east_asian = src_run.font.name_east_asian
            if src_run.font.size:
                run.font.size = src_run.font.size
            if src_run.font.bold is not None:
                run.font.bold = src_run.font.bold
            if src_run.font.italic is not None:
                run.font.italic = src_run.font.italic
            if src_run.font.underline is not None:
                run.font.underline = src_run.font.underline
            if src_run.font.color and src_run.font.color.rgb:
                run.font.color.rgb = src_run.font.color.rgb


def get_paragraph_style_name(para):
    """Get the style name of a paragraph, or None if not set."""
    if para.style:
        return para.style.name
    return None


def apply_template_styles(template_doc, target_doc, output_path):
    """
    Main function: apply template styles to target document content.
    """
    template_style_map = extract_style_info(template_doc)

    # Create new document based on template's structure
    new_doc = Document()

    # Copy template's style XML definitions into new document
    for style in template_doc.styles:
        try:
            style_xml = style.element.xml
            new_doc.styles.add_style(style.name, style.type, style.element)
        except Exception:
            pass

    # Process each paragraph from target document
    for i, para in enumerate(target_doc.paragraphs):
        # Create a new paragraph with the same text content
        new_para = new_doc.add_paragraph()

        # Copy the text content from the target paragraph
        # Preserve runs to maintain any run-level formatting that should be kept
        first = True
        for run in para.runs:
            if first:
                new_run = new_para.add_run(run.text)
                first = False
            else:
                new_run = new_para.add_run(run.text)

        # Get the original style name
        orig_style_name = get_paragraph_style_name(para)

        # Try to find a matching template style
        matched_style = find_matching_style(orig_style_name, template_style_map)

        # Apply the matched template style if found
        if matched_style and matched_style in new_doc.styles:
            try:
                new_para.style = new_doc.styles[matched_style]
            except (KeyError, AttributeError):
                pass

        # Copy paragraph-level formatting from the original
        copy_paragraph_formatting(para, new_para, template_style_map)

        # If no style matched, explicitly apply the Normal style from template
        if not matched_style:
            try:
                new_para.style = new_doc.styles['Normal']
            except (KeyError, AttributeError):
                pass

    # Process tables from target document
    for table in target_doc.tables:
        new_table = new_doc.add_table(rows=len(table.rows), cols=len(table.columns))

        for row_idx, row in enumerate(table.rows):
            for col_idx, cell in enumerate(row.cells):
                new_cell = new_table.rows[row_idx].cells[col_idx]
                # Copy cell text
                cell_text = ''.join(run.text for run in cell.paragraphs[0].runs) if cell.paragraphs else ''
                if cell.paragraphs:
                    new_cell.paragraphs[0].text = cell_text

    # Save the new document
    new_doc.save(output_path)
    return output_path


def main():
    # Paths (Windows-style, with raw strings to handle spaces)
    template_path = r'D:\text python\Textbook-to-Video-master\Textbook-to-Video-master\docs\moban.docx'
    target_path = r'D:\text python\Textbook-to-Video-master\Textbook-to-Video-master\docs\v6.docx'
    output_path = r'D:\text python\Textbook-to-Video-master\Textbook-to-Video-master\docs\v6_formatted.docx'

    # Verify files exist
    if not os.path.exists(template_path):
        print(f"ERROR: Template file not found: {template_path}")
        return
    if not os.path.exists(target_path):
        print(f"ERROR: Target file not found: {target_path}")
        return

    print("Reading template document...")
    template_doc = Document(template_path)
    template_styles = [s.name for s in template_doc.styles]
    print(f"  Template has {len(template_styles)} styles")

    print("Reading target document...")
    target_doc = Document(target_path)
    target_paragraphs = len(target_doc.paragraphs)
    target_tables = len(target_doc.tables)
    print(f"  Target has {target_paragraphs} paragraphs and {target_tables} tables")

    print("Applying template styles to target content...")
    output_path = apply_template_styles(template_doc, target_doc, output_path)
    print(f"Done! Output saved to: {output_path}")


if __name__ == '__main__':
    main()
