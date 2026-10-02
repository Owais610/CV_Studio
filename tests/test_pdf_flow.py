"""Contact wrapping, live links, and long contact pagination regressions."""
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_entries import engine
from cv_studio_pdf import SourceParagraph, contact_block
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import SimpleDocTemplate


class ContactFlowTests(unittest.TestCase):
    def builder(self, contacts):
        data = engine.migrate(engine.DEFAULT_DATA)
        data['contacts'] = contacts
        return engine.CVBuilder(data)

    def test_contacts_wrap_as_complete_entries(self):
        builder = self.builder([dict(text=text, url='') for text in (
            'London, United Kingdom', '+44 20 1234 5678', 'person@example.com',
            'linkedin.com/in/long-professional-name')])
        flow = contact_block(builder)
        canvas = Canvas(io.BytesIO())
        flow.wrapOn(canvas, 220, 700)
        self.assertGreater(len(flow.rows), 1)
        for items, used, height in flow.rows:
            self.assertLessEqual(used, 220.01)
            for paragraph, x in items:
                self.assertEqual(len(paragraph.blPara.lines), 1)
                self.assertLessEqual(x+paragraph.width, 220.01)
        flow.drawOn(canvas, 20, 500)
        self.assertEqual(len(builder.source_regions), 4)

    def test_oversized_contact_splits_without_text_or_link_loss(self):
        token = 'LongContactMarker'
        text = token*900
        target = 'https://example.com/profile'
        builder = self.builder([dict(text=text,url=target),dict(text='FinalContactMarker',url='')])
        output = io.BytesIO()
        doc = SimpleDocTemplate(output,pagesize=A4,leftMargin=60,rightMargin=60,
                                topMargin=60,bottomMargin=60)
        doc.build([contact_block(builder)])
        with engine.pymupdf.open(stream=output.getvalue(),filetype='pdf') as pdf:
            self.assertGreater(len(pdf), 1)
            visible = ''.join(page.get_text() for page in pdf).replace('\n','')
            self.assertEqual(visible.count(token),900)
            self.assertIn('FinalContactMarker',visible)
            self.assertTrue(all(any(link.get('uri')==target for link in page.get_links())
                                for page in pdf if token[:5] in page.get_text()))
            for region in builder.source_regions:
                x0,y0,x1,y1 = region['rect']
                self.assertTrue(0 <= x0 < x1 <= A4[0]+.1 and 0 <= y0 < y1 <= A4[1]+.1,region)

    def test_stacked_contacts_keep_each_link_and_source(self):
        builder = self.builder([dict(text='Email',url='person@example.com'),
                                dict(text='Portfolio',url='https://example.com')])
        output = io.BytesIO()
        doc = SimpleDocTemplate(output,pagesize=A4)
        doc.build([contact_block(builder,stacked=True)])
        self.assertEqual(builder.links,2)
        self.assertEqual([r['source'] for r in builder.source_regions],
                         [('contacts',0,'text'),('contacts',1,'text')])
        with engine.pymupdf.open(stream=output.getvalue(),filetype='pdf') as pdf:
            self.assertEqual({link.get('uri') for link in pdf[0].get_links()},
                             {'mailto:person@example.com','https://example.com'})

    def test_paragraph_split_keeps_measured_column_width(self):
        builder = self.builder([])
        paragraph = SourceParagraph('ColumnMarker readable paragraph text. '*90,builder.S['body'])
        canvas = Canvas(io.BytesIO())
        paragraph.wrapOn(canvas,200,700)
        fragments = paragraph.splitOn(canvas,450,130)
        self.assertEqual(len(fragments),2)
        self.assertLessEqual(fragments[0].width,200.01)
        self.assertFalse(contact_block(builder))


if __name__=='__main__':
    unittest.main()
